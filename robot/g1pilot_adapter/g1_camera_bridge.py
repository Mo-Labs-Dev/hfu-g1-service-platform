#!/usr/bin/env python3
"""
G1 Studio - Physical G1 Camera Bridge

Read-only camera access through Unitree SDK2.

Endpoints:
  GET /status    Camera status
  GET /snapshot  Latest JPEG frame
  GET /stream    MJPEG live stream
  GET /health    Service health

No robot motion commands are used.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.video.video_client import VideoClient


HOST = os.getenv("G1_CAMERA_HOST", "0.0.0.0")
PORT = int(os.getenv("G1_CAMERA_PORT", "8770"))
INTERFACE = os.getenv("G1_CAMERA_INTERFACE", "enP2p1s0")

CAMERA_INTERVAL = 0.15
STREAM_INTERVAL = 0.15
FRAME_TIMEOUT = 5.0

latest_frame: Optional[bytes] = None
latest_frame_time = 0.0
last_error: Optional[str] = None
frames_received = 0

frame_lock = threading.Lock()
stop_event = threading.Event()


def get_camera_status() -> dict:
    with frame_lock:
        age = (
            time.monotonic() - latest_frame_time
            if latest_frame_time
            else None
        )

        connected = (
            latest_frame is not None
            and age is not None
            and age < FRAME_TIMEOUT
        )

        return {
            "service": "g1-camera-bridge",
            "camera_connected": connected,
            "stream_available": connected,
            "source": "unitree-sdk2",
            "frames_received": frames_received,
            "frame_age_seconds": (
                round(age, 2) if age is not None else None
            ),
            "error": last_error,
        }


def camera_worker() -> None:
    global latest_frame
    global latest_frame_time
    global last_error
    global frames_received

    print(
        f"[camera] Initializing SDK2 on {INTERFACE}",
        flush=True,
    )

    ChannelFactoryInitialize(0, INTERFACE)

    client = VideoClient()
    client.SetTimeout(3.0)
    client.Init()

    print("[camera] VideoClient initialized", flush=True)

    while not stop_event.is_set():
        try:
            code, data = client.GetImageSample()

            if code != 0 or not data:
                with frame_lock:
                    last_error = f"SDK response: {code}"
                time.sleep(0.5)
                continue

            jpeg = bytes(data)

            if not jpeg.startswith(b"\xff\xd8"):
                with frame_lock:
                    last_error = "Received invalid JPEG data"
                time.sleep(0.5)
                continue

            with frame_lock:
                latest_frame = jpeg
                latest_frame_time = time.monotonic()
                frames_received += 1
                last_error = None

            time.sleep(CAMERA_INTERVAL)

        except Exception as exc:
            with frame_lock:
                last_error = str(exc)

            print(f"[camera] Error: {exc}", flush=True)
            time.sleep(1.0)


class CameraHandler(BaseHTTPRequestHandler):

    def log_message(self, format_string, *args):
        print(
            "[http] " + format_string % args,
            flush=True,
        )

    def send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def get_frame(self) -> Optional[bytes]:
        with frame_lock:
            if (
                latest_frame is None
                or time.monotonic() - latest_frame_time
                >= FRAME_TIMEOUT
            ):
                return None

            return latest_frame

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/status", "/health"):
            self.send_json(get_camera_status())
            return

        if path == "/snapshot":
            frame = self.get_frame()

            if frame is None:
                self.send_json(
                    {"error": "Camera frame unavailable"},
                    503,
                )
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(frame)
            return

        if path == "/stream":
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            previous_frame_time = 0.0

            try:
                while not stop_event.is_set():
                    with frame_lock:
                        frame = latest_frame
                        timestamp = latest_frame_time

                    if (
                        frame is None
                        or time.monotonic() - timestamp
                        >= FRAME_TIMEOUT
                        or timestamp == previous_frame_time
                    ):
                        time.sleep(STREAM_INTERVAL)
                        continue

                    previous_frame_time = timestamp

                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(
                        b"Content-Type: image/jpeg\r\n"
                    )
                    self.wfile.write(
                        f"Content-Length: {len(frame)}\r\n\r\n"
                        .encode("ascii")
                    )
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

                    time.sleep(STREAM_INTERVAL)

            except (BrokenPipeError, ConnectionResetError):
                pass

            return

        self.send_json({"error": "Not found"}, 404)


def main() -> None:
    worker = threading.Thread(
        target=camera_worker,
        daemon=True,
    )
    worker.start()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        CameraHandler,
    )
    server.daemon_threads = True

    print(
        f"[camera] HTTP bridge listening on {HOST}:{PORT}",
        flush=True,
    )

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
