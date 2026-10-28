
import asyncio
import json

from bleak import BleakScanner, BleakClient

import ble_uuids;

async def get_ip():

    while True:
        print("Scanning for BLE devices...")
        devices = await BleakScanner.discover()
        target = None

        for device in devices:
            print(f"Found device: {device.name} ({device.address})")
            if device.name == "BABY-CAM":
                target = device
                break

        if target is None:
            print("BABY-CAM not found, retrying in 5 seconds...")
            await asyncio.sleep(5)
            continue

        async with BleakClient(target.address) as client:
            ip = await client.read_gatt_char(ble_uuids.IP_CHAR_UUID)
            print("BABY-CAM IP:", ip.decode())
            break

    return json.loads(ip.decode())
        

