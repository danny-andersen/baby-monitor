#!/usr/bin/env python3

import os
import socket

import serial
import subprocess
import requests

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
                ser.write(f"<IP={ip}>\n".encode("ascii"))
            else:
                ser.write(b"<UNKNOWN_COMMAND>\n")

    except Exception as e:
        print(e)
        