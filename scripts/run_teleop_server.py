#!/usr/bin/env python3
"""
Standalone teleop server for the G1 Remote app joystick.

Mock mode (no robot, safe anywhere):
    G1_TELEOP_PIN=4821 python3 scripts/run_teleop_server.py --mock

Real robot (inside the g1pilot-dev container, robot in FSM 500):
    G1_TELEOP_PIN=4821 python3 scripts/run_teleop_server.py \
        --interface enP2p1s0

Run from the repository root. Requires: pip install fastapi uvicorn
"""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from robot.teleop.motion_backends import (  # noqa: E402
    MockMotionBackend,
    UnitreeMotionBackend,
)
from robot.teleop.teleop_api import create_teleop_router  # noqa: E402
from robot.teleop.teleop_controller import (  # noqa: E402
    TeleopController,
    TeleopLimits,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true",
                        help="Do not connect to the robot.")
    parser.add_argument("--interface", default="enP2p1s0")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--max-forward", type=float, default=0.30)
    parser.add_argument("--max-yaw", type=float, default=0.40)
    parser.add_argument("--no-robot-show", action="store_true",
                        help="Disable the visitor Robot Show gestures.")
    args = parser.parse_args()

    pin = os.environ.get("G1_TELEOP_PIN", "")
    if len(pin) < 4:
        sys.exit("Set G1_TELEOP_PIN (at least 4 digits) before starting.")

    if args.mock:
        backend = MockMotionBackend(verbose=True)
        print("[teleop] MOCK mode - no robot commands are sent.")
    else:
        backend = UnitreeMotionBackend(args.interface)
        print(f"[teleop] REAL robot on {args.interface}. "
              "Keep the physical E-stop in reach.")

    limits = TeleopLimits(
        max_vx_forward=min(args.max_forward, 0.6),
        max_yaw=min(args.max_yaw, 0.8),
        robot_show_enabled=not args.no_robot_show,
    )
    controller = TeleopController(backend, pin=pin, limits=limits)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        controller.start()
        try:
            yield
        finally:
            controller.shutdown()

    app = FastAPI(title="G1 Teleop", lifespan=lifespan)
    app.include_router(create_teleop_router(controller))

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
