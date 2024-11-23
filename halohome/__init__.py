import asyncio
import logging
from importlib import metadata
from typing import List

import aiohttp
import csrmesh
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

VERSION = metadata.version("halohome")
HOST = "https://api.avi-on.com"
TIMEOUT = 5

_LOGGER = logging.getLogger(__name__)


class HaloHomeError(Exception):
    pass


def _format_mac_address(mac_address: str) -> str:
    iterator = iter(mac_address.lower())
    pairs = zip(iterator, iterator)
    return ":".join(a + b for a, b in pairs)


class Entity:
    def __init__(
        self,
        location: "LocationConnection",
        avid: int,
        name: str,
    ):
        self.location = location
        self.avid = avid
        self.name = name

    async def set_brightness(self, brightness: int) -> bool:
        return await self.location.set_brightness(self.avid, brightness)

    async def set_color_temp(self, color: int) -> bool:
        return await self.location.set_color_temp(self.avid, color)

    def __repr__(self):
        return str(self)


class Device(Entity):
    def __init__(
        self,
        location: "LocationConnection",
        avid: int,
        name: str,
        mac_address: str,
    ):
        super().__init__(location, avid, name)
        self.mac_address = mac_address

    def __str__(self):
        return f"Device<{self.name} ({self.avid}), {self.mac_address}>"


class Group(Entity):
    def __str__(self):
        return f"Group<{self.name} ({self.avid})>"


class LocationConnection:
    CHARACTERISTIC_LOW = "c4edc000-9daf-11e3-8003-00025b000b00"
    CHARACTERISTIC_HIGH = "c4edc000-9daf-11e3-8004-00025b000b00"

    def __init__(
        self, location_id: str, passphrase: str, devices: List[dict], groups: List[dict], timeout: int = TIMEOUT
    ):
        self.devices = []
        self.groups = []
        self.mesh_connection = None
        self.location_id = location_id
        self.key = csrmesh.crypto.generate_key(passphrase.encode("ascii") + b"\x00\x4d\x43\x50")
        self.timeout = timeout

        for raw_device in devices:
            device_id = raw_device["device_id"]
            device_name = raw_device["device_name"]
            mac_address = raw_device["mac_address"]
            device = Device(self, device_id, device_name, mac_address)
            self.devices.append(device)

        for raw_group in groups:
            group_id = raw_group["group_id"]
            group_name = raw_group["group_name"]
            group = Group(self, group_id, group_name)
            self.groups.append(group)

    async def _priority_devices(self):
        scanned_devices = await BleakScanner.discover(return_adv=True)
        sorted_devices = sorted(scanned_devices.items(), key=lambda d: d[1][1].rssi)
        sorted_addresses = [d[0].lower() for d in sorted_devices]

        def priority(device: Device):
            try:
                return sorted_addresses.index(device.mac_address)
            except ValueError:
                return -1

        return sorted(self.devices, key=priority, reverse=True)

    async def _connect(self):
        for device in await self._priority_devices():
            try:
                client = BleakClient(device.mac_address, timeout=self.timeout)
                await client.connect()
                self.mesh_connection = client
                return
            except BleakError:
                pass

    def _create_packet(self, target_id: int, noun: int, value_bytes: bytearray) -> bytes:
        if target_id < 32896:
            group_id = target_id
            target_id = 0
        else:
            group_id = 0

        target_bytes = bytearray(target_id.to_bytes(2, byteorder="big"))
        group_bytes = bytearray(group_id.to_bytes(2, byteorder="big"))
        return bytes(
            [
                target_bytes[1],
                target_bytes[0],
                115,
                0,  # verb
                noun,
                group_bytes[0],
                group_bytes[1],
                0,  # id
                *value_bytes,
                0,
                0,
            ]
        )

    async def _send_packet(self, packet: bytes) -> bool:
        csrpacket = csrmesh.crypto.make_packet(self.key, csrmesh.crypto.random_seq(), packet)
        low = csrpacket[:20]
        high = csrpacket[20:]

        for _ in range(3):
            try:
                if self.mesh_connection is None:
                    await self._connect()

                await self.mesh_connection.write_gatt_char(self.CHARACTERISTIC_LOW, low)
                await self.mesh_connection.write_gatt_char(self.CHARACTERISTIC_HIGH, high)
                return True
            except Exception:
                self.mesh_connection = None
                _LOGGER.exception("Caught exception connecting to device")

        return False

    async def set_brightness(self, device_id: int, brightness: int) -> bool:
        packet = self._create_packet(device_id, 0x0A, bytes([brightness, 0, 0]))
        return await self._send_packet(packet)

    async def set_color_temp(self, device_id: int, color: int) -> bool:
        packet = self._create_packet(device_id, 0x1D, bytes([0x01, *bytearray(color.to_bytes(2, byteorder="big"))]))
        return await self._send_packet(packet)


class Connection:
    def __init__(self, locations: List[dict], timeout: int = TIMEOUT):
        self.devices = []
        self.groups = []
        self.timeout = timeout

        for raw_location in locations:
            location = LocationConnection(**raw_location)
            self.devices.extend(location.devices)
            self.groups.extend(location.groups)


async def _make_request(
    host: str,
    path: str,
    body: dict = None,
    auth_token: str = None,
    timeout: int = TIMEOUT,
):
    method = "GET" if body is None else "POST"
    url = host + path

    headers = {}
    if auth_token:
        headers["Accept"] = "application/api.avi-on.v3"
        headers["Authorization"] = f"Token {auth_token}"

    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=body, headers=headers, timeout=timeout) as response:
            return await response.json()


async def _load_devices(host: str, auth_token: str, location_id: str, timeout: int) -> List[dict]:
    response = await _make_request(
        host, f"locations/{location_id}/abstract_devices", auth_token=auth_token, timeout=timeout
    )
    raw_devices = response["abstract_devices"]
    devices = []

    for raw_device in raw_devices:
        if raw_device["type"] != "device":
            continue

        device_id = raw_device["avid"]
        device_name = raw_device["name"]
        mac_address = _format_mac_address(raw_device["friendly_mac_address"])
        device = {"device_id": device_id, "device_name": device_name, "mac_address": mac_address}
        devices.append(device)

    return devices


async def _load_groups(host: str, auth_token: str, location_id: str, timeout: int) -> List[dict]:
    response = await _make_request(host, f"locations/{location_id}/groups", auth_token=auth_token, timeout=timeout)
    raw_groups = response["groups"]
    groups = []

    for raw_group in raw_groups:
        group_id = raw_group["avid"]
        group_name = raw_group["name"]
        group = {"group_id": group_id, "group_name": group_name}
        groups.append(group)

    return groups


async def _load_location(host: str, auth_token: str, location_id: int, timeout: int) -> dict:
    response = await _make_request(host, f"locations/{location_id}", auth_token=auth_token, timeout=timeout)
    raw_location = response["location"]
    devices, groups = await asyncio.gather(
        _load_devices(host, auth_token, location_id, timeout), _load_groups(host, auth_token, location_id, timeout)
    )
    return {
        "location_id": raw_location["pid"],
        "passphrase": raw_location["passphrase"],
        "devices": devices,
        "groups": groups,
    }


async def _load_locations(host: str, auth_token: str, timeout: int) -> List[dict]:
    response = await _make_request(host, "user/locations", auth_token=auth_token, timeout=timeout)
    locations = []
    for raw_location in response["locations"]:
        location = await _load_location(host, auth_token, raw_location["pid"], timeout)
        locations.append(location)

    return locations


async def list_devices(
    email: str,
    password: str,
    host: str = HOST,
    timeout: int = TIMEOUT,
):
    if not host.endswith("/"):
        host += "/"

    login_body = {"email": email, "password": password}
    response = await _make_request(host, "sessions", login_body, timeout=timeout)
    if "credentials" not in response:
        raise HaloHomeError("Invalid credentials for HALO Home")
    auth_token = response["credentials"]["auth_token"]

    return await _load_locations(host, auth_token, timeout)
