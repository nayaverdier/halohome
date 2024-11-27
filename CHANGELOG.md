# Changelog

## 0.7.0 2024-11-26

Courtesy of @oyvindkinsey:

- Add support for fetching groups from Avi-on's API

### Breaking changes
- device.device_id is now device.avid to better reflect the underlying datamodel

## 0.6.0 2024-11-22

Courtesy of @oyvindkinsey:

- Update the use of Avi-on's API to the current v3
- Fix incorrect use of avid (this now also supports groups etc)
- Add new function for constructing packets that work for both devices and groups
- Remove use of deprecated BLEDevices.rssi
- Replaced product_ids filtering with a type filter

## 0.5.0 2022-01-25

- Sort devices by RSSI before connecting to avoid unnecessary delay

## 0.4.0 2021-11-08

(BREAKING)

- Remove support for `user_id` (username/email is sufficient)
- Support offline loading of devices (e.g. in case of internet outage)

## 0.3.0 2021-10-25

- Read `user_id` to provide a permanent ID for the HALO Home account

## 0.2.1 2021-10-23

- Raise HaloHomeError when credentials are not valid

## 0.2.0 2021-10-21

- Support mesh communication (only need to connect to a single device
  to control all of them)
- Make network and bluetooth connections async

## 0.1.0 2021-10-17

- Initial release
