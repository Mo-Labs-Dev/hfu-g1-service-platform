#!/usr/bin/env python3
"""
G1 Studio physical speech bridge.

Exposes a localhost-only HTTP endpoint for speaking text
through the Unitree G1 built-in speaker.

No locomotion, arm, or FSM commands are implemented here.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient


HOST = "127.0.0.1"
PORT = 8766
INTERFACE = "enP2p1s0"
MAX_TEXT_LENGTH = 450

speech_lock = threading.Lock()
audio_client: AudioClient | None = None


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_json(404, {"error": "Not found"})
            return

        self.send_json(200, {
            "status": "ready",
            "service": "g1-speech",
            "interface": INTERFACE,
        })

    def do_POST(self) -> None:
        if self.path != "/speak":
            self.send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid content length"})
            return

        if not 0 < length <= 4096:
            self.send_json(400, {"error": "Invalid request size"})
            return

        try:
            request = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "Invalid JSON"})
            return

        if not isinstance(request, dict):
            self.send_json(400, {"error": "Expected JSON object"})
            return

        text = request.get("text")

        if not isinstance(text, str):
            self.send_json(400, {"error": "Text must be a string"})
            return

        text = text.strip()

        if not text or len(text) > MAX_TEXT_LENGTH:
            self.send_json(400, {"error": "Invalid text length"})
            return

        if not speech_lock.acquire(blocking=False):
            self.send_json(409, {"error": "Robot is already speaking"})
            return

        try:
            if audio_client is None:
                self.send_json(503, {"error": "Audio unavailable"})
                return

            code = audio_client.TtsMaker(text, 1)

            if code != 0:
                self.send_json(502, {
                    "error": "Unitree TTS failed",
                    "code": code,
                })
                return

            self.send_json(200, {
                "accepted": True,
                "code": code,
            })

        except Exception as error:
            print(f"[G1 Speech] {error}", flush=True)
            self.send_json(502, {"error": "Robot speech request failed"})
        finally:
            speech_lock.release()

    def log_message(self, format_string, *args) -> None:
        return


def main() -> None:
    global audio_client

    ChannelFactoryInitialize(0, INTERFACE)

    audio_client = AudioClient()
    audio_client.SetTimeout(10.0)
    audio_client.Init()

    server = ThreadingHTTPServer((HOST, PORT), Handler)

    print(
        f"[G1 Speech] Ready at http://{HOST}:{PORT}",
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()