import time
from importlib import resources
from multiprocessing import Pool
from typing import List

import csrmesh
import requests
from bluepy import btle

VERSION = resources.read_text("halohome", "VERSION").strip()


class HaloHomeError(Exception):
    pass


def _format_mac_address(mac_address: str) -> str:
    iterator = iter(mac_address)
    pairs = zip(iterator, iterator)
    return ":".join(a + b for a, b in pairs)


class Device:
    CHARACTERISTIC_LOW = btle.UUID("c4edc000-9daf-11e3-8003-00025b000b00")
    CHARACTERISTIC_HIGH = btle.UUID("c4edc000-9daf-11e3-8004-00025b000b00")
    KEY_SUFFIX = b"\x00\x4d\x43\x50"

    def __init__(self, device: dict):
        self.connection = device["connection"]
        self.device_id = device["device_id"]
        self.pid = device["pid"]
        self.device_name = device["name"]
        self.mac_address = _format_mac_address(device["friendly_mac_address"])
        self.key = csrmesh.crypto.generate_key(device["passphrase"].encode("ascii") + self.KEY_SUFFIX)
        self.peripheral = None

    def _connect(self):
        self.peripheral = btle.Peripheral(self.mac_address, addrType=btle.ADDR_TYPE_PUBLIC)
        self._load_characteristics()

    def _load_characteristics(self):
        # extract the low/high characteristic handles to write data
        characteristics = self.peripheral.getCharacteristics()
        for characteristic in characteristics:
            if characteristic.uuid == self.CHARACTERISTIC_LOW:
                self.low_handle = characteristic.getHandle()
            elif characteristic.uuid == self.CHARACTERISTIC_HIGH:
                self.high_handle = characteristic.getHandle()

    def set_brightness(self, brightness: int) -> bool:
        packet = bytes([0x80 + self.device_id]) + b"\x80s\x00\n\x00\x00\x00" + bytes([brightness]) + bytes(4)
        return self._send_packet(packet)

    def _send_packet(self, packet: bytes) -> bool:
        csrpacket = csrmesh.crypto.make_packet(self.key, csrmesh.crypto.random_seq(), packet)
        low = csrpacket[:20]
        high = csrpacket[20:]

        start = time.monotonic()

        while True:
            # timeout after 10 seconds
            if time.monotonic() - start >= 10:
                return False

            try:
                if self.peripheral is None:
                    self._connect()

                self.peripheral.writeCharacteristic(self.low_handle, low, withResponse=True)  # type: ignore
                self.peripheral.writeCharacteristic(self.high_handle, high, withResponse=True)  # type: ignore
                return True
            except Exception:
                self.peripheral = None
                time.sleep(0.1)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"Device<{self.device_name}, {self.mac_address}>"


class Connection:
    def __init__(self, auth_token: str, host: str, product_ids: List[int], timeout: int):
        self.auth_token = auth_token
        self.host = host
        self.product_ids = product_ids
        self.timeout = timeout

    def list_devices(self):
        devices = []

        device_id_offset = None
        for location in self._locations():
            location_id = str(location["id"])
            for device in self._location_devices(location_id):
                if device["product_id"] in self.product_ids:
                    if device_id_offset is None:
                        device_id_offset = device["avid"]

                    device["connection"] = self
                    device["passphrase"] = location["passphrase"]
                    device["device_id"] = device["avid"] - device_id_offset
                    devices.append(device)

        with Pool(25) as pool:
            return pool.map(Device, devices)

    def _locations(self) -> List[dict]:
        return self._request("locations")["locations"]

    def _location_devices(self, location_id: str) -> List[dict]:
        return self._request(f"locations/{location_id}/abstract_devices")["abstract_devices"]

    def _request(self, path: str, body: dict = None):
        method = "GET" if body is None else "POST"
        url = self.host + path
        headers = {"Authorization": f"Token {self.auth_token}", "Accept": "application/api.avi-on.v2"}

        return requests.request(method, url, headers=headers, json=body, timeout=self.timeout).json()


def connect(
    email: str,
    password: str,
    host: str = "https://api.avi-on.com",
    product_ids: List[int] = None,
    timeout: int = 5,
):
    if not host.endswith("/"):
        host += "/"

    if product_ids is None:
        product_ids = [93]

    login_url = host + "sessions"
    login_body = {"email": email, "password": password}

    response = requests.post(login_url, json=login_body, timeout=timeout)

    if response.status_code >= 300:
        raise Exception("Unable to login to Avi-On: {response.text}")

    auth_token = response.json()["credentials"]["auth_token"]

    return Connection(auth_token, host, product_ids, timeout)
