#!/usr/bin/env python3

import os
from time import sleep
import socket

import serial
import subprocess
import requests
import json
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from keys import AES_KEY_HEX, NONCE_SIZE

ser = serial.Serial(
    '/dev/serial0',
    115200,
    bytesize=8,
    parity='N',
    stopbits=1,
    timeout=1
)

print("Waiting for commands...")

def camera_running():
    try:
        response = requests.get(
            "http://localhost:8081/health",
            timeout=2
        )

        response.raise_for_status()

        health = response.json()

        return health.get("camera_ok", False) is True

    except Exception as e:
        print(f"Camera health check failed: {e}")
        return False
    
def send_status():
    camera = "is running" if camera_running() else "has stopped"

    ser.write(f"<OK,CAMERA={camera}>\n".encode())
              

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Doesn't actually send anything
        s.connect(("8.8.8.8", 80))

        ip = s.getsockname()[0]

        s.close()

        return ip

    except Exception:
        return "UNKNOWN"
    
def get_ap():
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True,
            text=True,
            check=True
        )

        return result.stdout.strip()

    except Exception:
        return "UNKNOWN"

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
    # print(f"Decrypted JSON: {data}")
    if not all(k in data for k in ("ssid", "password")):
        raise ValueError("Missing fields in decrypted JSON")

    return data

def connect_wifi(data):

    credentials = decrypt_payload(data)

    ssid = credentials.get("ssid")
    password = credentials.get("password")

    print(f"\nConnecting to WiFi: {ssid}")

    # Build nmcli command

    command = [
        "sudo",
        "-n",
        "nmcli",
        "device",
        "wifi",
        "rescan",
    ]
    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30
        )

    except subprocess.TimeoutExpired:
        print("WiFi rescan timed out")
        return False
    except FileNotFoundError:
        print("nmcli not found. Is NetworkManager installed?")
        return False

    
    sleep(1)  # Wait for rescan to complete

    command = [
        "sudo",
        "-n",
        "nmcli",
        "connection",
        "add",
        "type",
        "wifi",
        "con-name",
        ssid,
        "ssid",
        ssid
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10
        )

    except subprocess.TimeoutExpired:
        print("WiFi add timed out")
        return False
    
    if password:
        command = [
            "sudo",
            "-n",
            "nmcli",
            "connection",
            "modify",
            ssid,
            "wifi-sec.key-mgmt",
            "wpa-psk",
            "wifi-sec.psk",
            password
        ]
        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10
            )
        except subprocess.TimeoutExpired:
            print("WiFi modify timed out")
            return False

    command = [
        "sudo",
        "nmcli",
        "connection",
        "up",
        ssid
    ]

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


while True:
    try:
        line = ser.readline().decode(
            'ascii',
            errors='ignore'
        ).strip()
        # data = ser.readline()
        # print("Raw:", data)
        # print("Hex:", data.hex())
        # line = data.decode('utf-8', errors='replace').strip()

        if line.startswith("<") and line.endswith(">"):
            # print("Valid:", line)

            if not line:
                continue

            # print(f"Received: {line}")

            if line == "<STATUS>":
                send_status()
                ser.flush()

            elif line == "<SHUTDOWN>":
                ser.write(b"<SHUTTING_DOWN>\n")
                ser.flush()

                subprocess.run([
                    "sudo",
                    "shutdown",
                    "-h",
                    "now"
                ])
            elif line == "<GET_IP>":
                ip = get_ip()
                ap = get_ap()

                ser.write(f"<IP={ip},AP={ap}>\n".encode("ascii"))
            elif "<SET_AP=" in line:
                # Extract the Base64-encoded payload
                start = line.find("<SET_AP=") + len("<SET_AP=")
                end = line.find(">", start)
                if end == -1:
                    ser.write(b"<INVALID_COMMAND>\n")
                    continue
                encoded_payload = line[start:end]
                try:
                    success = connect_wifi(encoded_payload)
                    if success:
                        ip = get_ip()
                        ap = get_ap()
                        ser.write(f"<IP={ip},AP={ap}>\n".encode("ascii"))
                    else:
                        ser.write(b"<WIFI_FAILED>\n")
                except Exception as e:
                    ser.write(b"<WIFI_INVALID_PAYLOAD>\n")
                    continue
            else:
                ser.write(b"<UNKNOWN_COMMAND>\n")

    except Exception as e:
        print(e)
        