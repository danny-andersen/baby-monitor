
import asyncio
import json
import base64
import subprocess
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


from bleak import BleakScanner, BleakClient

from ble_uuids import AES_KEY_HEX, BLE_TIMEOUT, IP_CHAR_UUID, NONCE_SIZE, TAG_SIZE, BLE_DEVICE_NAME, SCAN_TIMEOUT;

async def get_ip():

    print("Scanning for BLE devices...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad:
            d.name == BLE_DEVICE_NAME or
            ad.local_name == BLE_DEVICE_NAME,
        timeout=SCAN_TIMEOUT
    )
    if device is None:
        print(f"{BLE_DEVICE_NAME} BLE device not found")
        return None

    print(f"Found device: {device.name} ({device.address})")

    async with BleakClient(device.address, timeout=BLE_TIMEOUT) as client:
        print(f"Connected to {device.name} ({device.address})")
        print(f"BLE MTU: {client.mtu_size}")
        ip = await client.read_gatt_char(IP_CHAR_UUID)
        encrypted_ip = ip.decode("ascii".strip())
        if not encrypted_ip:
            raise RuntimeError(
                "BLE characteristic contains no data"
            )

        print(f"Received {len(encrypted_ip)} encrypted characters")

        # Decrypt

        credentials = decrypt_payload(encrypted_ip)

        print("\nDecrypted WiFi information:")
        print("SSID:", credentials["ssid"])
        print("ESP32 IP:", credentials["ip"])
        print("Password: [hidden]")

        return credentials
        

# ============================================================
# AES-256-GCM DECRYPTION
# ============================================================

def decrypt_payload(encoded):

    key = bytes.fromhex(AES_KEY_HEX)

    if len(key) != 32:
        raise ValueError("AES key must be exactly 32 bytes")

    # Decode Base64

    payload = base64.b64decode(encoded, validate=True)

    if len(payload) < 28:
        raise ValueError("Encrypted payload is too short")

    # Arduino format:
    # 12-byte nonce + ciphertext + 16-byte GCM tag

    nonce = payload[:NONCE_SIZE]
    ciphertext_and_tag = payload[NONCE_SIZE:]

    # AES-GCM automatically verifies the authentication tag

    aes = AESGCM(key)

    plaintext = aes.decrypt(
        nonce,
        ciphertext_and_tag,
        None
    )

    # Convert decrypted JSON

    data = json.loads(plaintext.decode("utf-8"))
    print(f"Decrypted JSON: {data}")
    if not all(k in data for k in ("ssid", "password", "ip")):
        raise ValueError("Missing fields in decrypted JSON")

    return data


# ============================================================
# CONNECT TO WIFI USING NETWORK MANAGER
# ============================================================

def connect_wifi(ssid, password):

    print(f"\nConnecting to WiFi: {ssid}")

    # Build nmcli command

    command = [
        "nmcli",
        "--wait", "30",
        "device",
        "wifi",
        "connect",
        ssid
    ]

    if password:
        command += ["password", password]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=40
        )

        if result.returncode == 0:

            print("WiFi connection successful")

            print(result.stdout.strip())

            return True

        print("WiFi connection failed")
        print(result.stderr.strip())

        return False

    except subprocess.TimeoutExpired:

        print("WiFi connection timed out")
        return False

    except FileNotFoundError:

        print("nmcli not found. Is NetworkManager installed?")
        return False

