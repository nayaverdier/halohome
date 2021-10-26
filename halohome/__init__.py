from importlib import resources
from typing import Iterable, List

import aiohttp
import csrmesh
from bleak import BleakClient
from bleak.exc import BleakError

VERSION = resources.read_text("halohome", "VERSION").strip()


class HaloHomeError(Exception):
    pass


def _format_mac_address(mac_address: str) -> str:
    iterator = iter(mac_address)
    pairs = zip(iterator, iterator)
    return ":".join(a + b for a, b in pairs)


class Device:
    def __init__(
        self,
        connection: "LocationConnection",
        device_id: int,
        device_name: str,
        pid: str,
        mac_address: str,
    ):
        self.connection = connection
        self.device_id = device_id
        self.device_name = device_name
        self.pid = pid
        self.mac_address = mac_address

    async def set_brightness(self, brightness: int) -> bool:
        return await self.connection.set_brightness(self.device_id, brightness)

    async def set_color_temp(self, color: int) -> bool:
        return await self.connection.set_color_temp(self.device_id, color)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"Device<{self.device_name} ({self.device_id}), {self.mac_address}>"


class LocationConnection:
    CHARACTERISTIC_LOW = "c4edc000-9daf-11e3-8003-00025b000b00"
    CHARACTERISTIC_HIGH = "c4edc000-9daf-11e3-8004-00025b000b00"

    def __init__(self, connection: "Connection", location_id: str, passphrase: str, timeout: int):
        self.devices = []
        self.connection = connection
        self.mesh_connection = None
        self.location_id = location_id
        self.key = csrmesh.crypto.generate_key(passphrase.encode("ascii") + b"\x00\x4d\x43\x50")
        self.timeout = timeout

    @classmethod
    async def create(
        cls,
        connection: "Connection",
        location_id: str,
        passphrase: str,
        product_ids: Iterable[int],
        timeout: int,
    ) -> "LocationConnection":
        instance = cls(connection, location_id, passphrase, timeout)

        response = await connection._request(f"locations/{location_id}/abstract_devices")
        raw_devices = response["abstract_devices"]
        device_id_offset = None
        for raw_device in raw_devices:
            if raw_device["product_id"] not in product_ids:
                continue

            device_id_offset = device_id_offset or raw_device["avid"]

            device_id = raw_device["avid"] - device_id_offset
            pid = raw_device["pid"]
            device_name = raw_device["name"]
            mac_address = _format_mac_address(raw_device["friendly_mac_address"])

            device = Device(instance, device_id, device_name, pid, mac_address)
            instance.devices.append(device)

        return instance

    async def _connect(self):
        for device in self.devices:
            try:
                client = BleakClient(device.mac_address, timeout=self.timeout)
                await client.connect()
                self.mesh_connection = client
                return
            except BleakError:
                pass

    async def _send_packet(self, packet: bytes) -> bool:
        csrpacket = csrmesh.crypto.make_packet(self.key, csrmesh.crypto.random_seq(), packet)
        low = csrpacket[:20]
        high = csrpacket[20:]

        tries = 3
        while tries > 0:
            tries -= 1

            try:
                if self.mesh_connection is None:
                    await self._connect()

                await self.mesh_connection.write_gatt_char(self.CHARACTERISTIC_LOW, low)
                await self.mesh_connection.write_gatt_char(self.CHARACTERISTIC_HIGH, high)
                return True
            except Exception:
                self.mesh_connection = None

        return False

    async def set_brightness(self, device_id: int, brightness: int) -> bool:
        packet = bytes([0x80 + device_id, 0x80, 0x73, 0, 0x0A, 0, 0, 0, brightness, 0, 0, 0, 0])
        return await self._send_packet(packet)

    async def set_color_temp(self, device_id: int, color: int) -> bool:
        color_bytes = bytearray(color.to_bytes(2, byteorder="big"))
        packet = bytes([0x80 + device_id, 0x80, 0x73, 0, 0x1D, 0, 0, 0, 0x01, *color_bytes, 0, 0])
        return await self._send_packet(packet)


class Connection:
    def __init__(self, auth_token: str, user_id: int, host: str, product_ids: Iterable[int], timeout: int):
        self.auth_token = auth_token
        self.user_id = user_id
        self.host = host
        self.product_ids = product_ids
        self.timeout = timeout

    async def list_devices(self):
        devices = []

        for location in await self._locations():
            location_id = str(location["id"])
            location_connection = await LocationConnection.create(
                self,
                location_id,
                location["passphrase"],
                self.product_ids,
                self.timeout,
            )
            devices.extend(location_connection.devices)

        return devices

    async def _locations(self) -> List[dict]:
        response = await self._request("locations")
        return response["locations"]

    async def _request(self, path: str, body: dict = None):
        return await make_request(self.host, path, body, self.auth_token, self.timeout)


async def make_request(
    host: str,
    path: str,
    body: dict = None,
    auth_token: str = None,
    timeout: int = 5,
):
    method = "GET" if body is None else "POST"
    url = host + path

    headers = {}
    if auth_token:
        headers["Accept"] = "application/api.avi-on.v2"
        headers["Authorization"] = f"Token {auth_token}"

    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=body, headers=headers, timeout=timeout) as response:
            return await response.json()


async def connect(
    email: str,
    password: str,
    host: str = "https://api.avi-on.com",
    product_ids: Iterable[int] = (93,),
    timeout: int = 5,
):
    if not host.endswith("/"):
        host += "/"

    login_body = {"email": email, "password": password}
    response = await make_request(host, "sessions", login_body, timeout=timeout)

    if "credentials" not in response:
        raise HaloHomeError("Invalid credentials for HALO Home")

    auth_token = response["credentials"]["auth_token"]

    user_response = await make_request(host, "user", auth_token=auth_token, timeout=timeout)

    if "user" not in user_response:
        raise HaloHomeError("Unexpected error reading HALO Home user data")

    user_id = user_response["user"]["id"]

    return Connection(auth_token, user_id, host, product_ids, timeout)
