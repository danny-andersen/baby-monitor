
#!/usr/bin/env python3

import io
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from picamera2 import Picamera2
from libcamera import Transform
from PIL import Image


# Configuration
HOST = "0.0.0.0"       # Listen on all network interfaces
PORT = 8081
WIDTH = 860
HEIGHT = 610
FPS = 15
JPEG_QUALITY = 75


class CameraStream:
    def __init__(self):
        self.camera = Picamera2()

        config = self.camera.create_video_configuration(
            main={
                "size": (WIDTH, HEIGHT),
                "format": "RGB888"
            },
            controls={
                "FrameRate": FPS
            },
            transform=Transform(hflip=1, vflip=1),
            buffer_count=4
        )

        self.camera.configure(config)
        self.camera.start()

        self.last_frame_time = 0.0
        self.lock = threading.Lock()
        self.jpeg = None
        self.running = True

        # One capture thread shared by all browser clients
        self.thread = threading.Thread(
            target=self.capture_loop,
            daemon=True
        )
        self.thread.start()

    def capture_loop(self):
        while self.running:
            try:
                frame = self.camera.capture_array("main")

                # Encode to JPEG
                image = Image.fromarray(frame)
                output = io.BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=JPEG_QUALITY
                )

                with self.lock:
                    self.jpeg = output.getvalue()
                    self.last_frame_time = time.monotonic()

            except Exception as exc:
                print(f"Camera capture error: {exc}")
                time.sleep(0.2)

    def get_frame(self):
        with self.lock:
            return self.jpeg

    def is_healthy(self):
        with self.lock:
            return (
                self.last_frame_time > 0
                and time.monotonic() - self.last_frame_time < 3.0
            )

    def close(self):
        self.running = False
        self.thread.join(timeout=2)
        self.camera.stop()
        self.camera.close()


camera = None


class CameraHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html = b"""<!DOCTYPE html>
<html>
<head>
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<style>
body {
    margin: 0;
    background: #222;
    color: white;
    font-family: sans-serif;
    text-align: center;
}
img {
    width: 100%;
    max-width: 1024px;
    height: 100%;
}
</style>
</head>
<body>
<img src="/stream" alt="Live camera stream">
</body>
</html>"""

            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        elif self.path == "/stream":
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame"
            )
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            try:
                while True:
                    frame = camera.get_frame()

                    if frame is None:
                        time.sleep(0.05)
                        continue

                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(
                        b"Content-Type: image/jpeg\r\n"
                    )
                    self.wfile.write(
                        f"Content-Length: {len(frame)}\r\n\r\n".encode()
                    )
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")

                    # Avoid sending the same frame excessively
                    time.sleep(1.0 / FPS)

            except (BrokenPipeError, ConnectionResetError, OSError):
                # Browser disconnected
                pass

        elif self.path == "/snapshot":
            frame = camera.get_frame()

            if frame is None:
                self.send_error(503, "Camera not ready")
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)

        elif self.path == "/health":
            import json

            healthy = camera.is_healthy()
            body = json.dumps({
                "camera_ok": healthy
            }).encode()

            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        # Keep console output quiet for frequent stream requests
        if self.path != "/stream":
            super().log_message(fmt, *args)


def main():
    global camera

    camera = CameraStream()

    server = ThreadingHTTPServer((HOST, PORT), CameraHandler)

    print(f"Camera ready: http://<raspberry-pi-ip>:{PORT}/")
    print(f"Stream URL:   http://<raspberry-pi-ip>:{PORT}/stream")
    print(f"Snapshot URL: http://<raspberry-pi-ip>:{PORT}/snapshot")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping camera server...")
    finally:
        server.server_close()
        camera.close()


if __name__ == "__main__":
    main()
