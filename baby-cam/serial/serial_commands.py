#!/usr/bin/env python3

import os
import serial
import subprocess

ser = serial.Serial(
    '/dev/serial0',
    115200,
    bytesize=8,
    parity='N',
    stopbits=1,
    timeout=1
)

print("Waiting for commands...")

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
                msg = "<OK>\n"
                ser.write(ser.write(msg.encode('ascii')))
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

            else:
                ser.write(b"<UNKNOWN_COMMAND>\n")

    except Exception as e:
        print(e)
        