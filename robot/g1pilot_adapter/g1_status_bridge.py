from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient


HOST = "127.0.0.1"
PORT = 8767
INTERFACE = "enP2p1s0"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("g1-status-bridge")

client_lock = threading.Lock()


def create_client() -> LocoClient:
    ChannelFactoryInitialize(0, INTERFACE)

    client = LocoClient()
    client.SetTimeout(3.0)
    client.Init()

    return client


robot_client = create_client()


def get_live_status() -> dict:
    with client_lock:
        code, fsm_id = robot_client.GetFsmId()

    if code != 0 or fsm_id is None:
        raise RuntimeError(
            f"GetFsmId failed: response={code}"
        )

    return {
        "connected": True,
        "source": "physical_g1",
        "fsm_id": int(fsm_id),
        "locomotion_mode": int(fsm_id) == 500,
        "motion_enabled": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond(
                200,
                {
                    "status": "ok",
                    "service": "g1-status-bridge",
                    "mode": "read_only",
                },
            )
            return

        if self.path != "/status":
            self.respond(404, {"error": "Not found"})
            return

        try:
            self.respond(200, get_live_status())
        except Exception:
            logger.exception("Unable to read G1 FSM")

            self.respond(
                503,
                {
                    "connected": False,
                    "source": "physical_g1",
                    "fsm_id": None,
                    "locomotion_mode": False,
                    "motion_enabled": False,
                    "error": "Physical G1 status unavailable",
                },
            )

    def do_POST(self) -> None:
        self.respond(
            405,
            {"error": "Motion commands are disabled"},
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    logger.info(
        "G1 read-only status bridge listening on %s:%s",
        HOST,
        PORT,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()