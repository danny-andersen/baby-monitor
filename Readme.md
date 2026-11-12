# Baby Monitor

## Overview 
A project that uses an ESP32-C6 microcontroller to provide an audio streaming feed and overall power control, a PiZero 2W with a Picamera for a Video feed and a Raspberry PI 4B monitor. This was built to provide a baby monitor using the local Wifi as the default transport. 

## Communication methods and protocols

### Overview

All three units communicate via a wifi link: the ESP32 to provide an I2S audio stream via a HTTP server and the Pi Zero 2W a JPEG stream via a HTTP server. Both also provide status end points that provides a JSON string providing various internal conditions.

### Determining IP addresses

A key constraint therefore is that all three devices must be connected to the same access point and that the monitor can discover which IP addresses the two devices are listening on. 

To do this, when the ESP32-C6 starts up, it will start to advertise via bluetooth (BLE), the AP name (i.e. SSID) and its assigned IP address. The monitor will locally save the URLs that it last connected to the remote audio and video streams; when it starts up, it uses the status URL to try and connect to the ESP32-C6 to ensure that it is listening on the same address as last time. If it **cannot** get a valid response from this URL, it will listen to the BLE characteristic adverstisement to get the AP name and IP address of the ESP32-C6. If it is connected to a different AP, the monitor will reconnect to this AP. Note that once the monitor has connected to the BLE server, the ESP32-C6 will, after a short delay, turn off the BLE server as this interferes with the Wifi operation (they share the same aerial on the ESP32-C6).

The monitor will then use this IP address to get the status JSON, which will contain the IP address of the video stream (if it has been started). Note that the ESP32-C6 controls the power to the PIZero and will only turn on the PI if the monitor requests video (via another URL). It will only turn on the PI if there is sufficient power to do so, i.e. the battery level is above 60%, even if the battery is charging. This prevents power supply issues and prevents the battery from being discharged to low (the PIZero consumes 3 - 5x the power of the ESP32).

 The ESP32 has a serial (UART) link to the PIZero, which it uses to determine the status of the PIZero and to also query its IP address; these are added to the status JSON, to allow the monitor to determine the IP address of the video stream. 

### No known Wifi AP

 In most situations, all three devices will be pre-configured with the same Wifi AP names and passwords and so allowing all three devices to connect to the same local network. In the event that the ESP32 cannot connect to an access point, it will start its own access point with a pre-configured name and password, allowing the monitor to connect to it. This is less than ideal, particularly when serving a video stream. In these situations, a video stream will not be allowed and the PIZero will not be powered on.

 To allow a new Wifi AP to be configured, under this situation, the ESP32 will host a web page that allows the entry of a new AP name and password. If the ESP32 successfully connects to this, it will store them in its non-volatile memory. It will also provide these via an encrypted BLE characteristic that the monitor will also read and apply as well as to the PIZero, after it boots, via the serial interface.
 