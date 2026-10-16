from __future__ import annotations

import hmac
import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.default import unitree_go_msg_dds__SportModeState_
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "127.0.0.1"
PORT = 8767
INTERFACE = "enP2p1s0"

FSM_GET_ID_API = 7001

ALLOW_POSTURE_COMMANDS = (
    os.getenv("G1_ALLOW_POSTURE_COMMANDS") == "1"
)
ALLOW_LOCOMOTION_COMMANDS = (
    os.getenv("G1_ALLOW_LOCOMOTION_COMMANDS") == "1"
)

CONTROL_TOKEN = os.getenv("G1_BRIDGE_TOKEN", "")

# SAFETY: physical SDK velocity output remains disabled.
PHYSICAL_MOTION_ENABLED = False

MAX_VX = 0.05
MAX_VY = 0.05
MAX_OMEGA = 0.10

WATCHDOG_TIMEOUT = 0.300
WATCHDOG_INTERVAL = 0.025

MODES = {
    "damp": {
        "source": 0,
        "target": 1,
        "permission": "posture",
    },
    "stand_up": {
        "source": 1,
        "target": 4,
        "permission": "posture",
    },
    "start_locomotion": {
        "source": 4,
        "target": 500,
        "permission": "locomotion",
    },
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("g1-status-bridge")

client_lock = threading.Lock()
motion_lock = threading.RLock()


# ============================================================
# SDK INITIALIZATION
# ============================================================

def create_client() -> LocoClient:
    ChannelFactoryInitialize(0, INTERFACE)
    client = LocoClient()
    client.SetTimeout(3.0)
    client.Init()
    return client


robot_client = create_client()


# Live state feedback is independent of the velocity command API.
# A message-type field alone is not proof that the robot publishes this topic.
class LiveMotionFeedback:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_received = None
        self.velocity = None
        self.yaw_speed = None
        self.subscriber = None
        self.error = None

    def callback(self, message):
        try:
            velocity = [float(v) for v in message.velocity]
            yaw_speed = float(message.yaw_speed)
            if len(velocity) < 2 or not all(math.isfinite(v) for v in velocity) or not math.isfinite(yaw_speed):
                return
            with self.lock:
                self.velocity = velocity
                self.yaw_speed = yaw_speed
                self.last_received = time.monotonic()
        except Exception:
            logger.exception("Invalid sport-mode feedback")

    def start(self):
        try:
            self.subscriber = ChannelSubscriber("rt/sportmodestate", unitree_go_msg_dds__SportModeState_)
            self.subscriber.Init(self.callback, 10)
            logger.info("Sport-mode feedback subscriber started")
        except Exception as error:
            self.error = str(error)
            logger.exception("Sport-mode feedback unavailable")

    def status(self):
        with self.lock:
            age = None if self.last_received is None else time.monotonic() - self.last_received
            return {
                "feedback_received": self.last_received is not None,
                "feedback_fresh": age is not None and age <= 0.5,
                "feedback_age_ms": None if age is None else round(age * 1000),
                "measured_velocity": self.velocity,
                "measured_yaw_speed": self.yaw_speed,
                "feedback_error": self.error,
            }


motion_feedback = LiveMotionFeedback()



# ============================================================
# EXISTING FSM FUNCTIONS
# ============================================================

def posture_available() -> bool:
    return ALLOW_POSTURE_COMMANDS and bool(CONTROL_TOKEN)


def locomotion_available() -> bool:
    return ALLOW_LOCOMOTION_COMMANDS and bool(CONTROL_TOKEN)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_fsm_id(data) -> int:
    if data is None:
        raise RuntimeError("GET FSM ID returned no data")

    if isinstance(data, bool):
        raise RuntimeError("Unexpected boolean FSM response")

    if isinstance(data, (int, float)):
        return int(data)

    if isinstance(data, bytes):
        data = data.decode("utf-8")

    if isinstance(data, str):
        value = data.strip()
        if not value:
            raise RuntimeError("Empty FSM response")

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            try:
                return int(value)
            except ValueError as error:
                raise RuntimeError(
                    f"Unable to parse FSM: {value!r}"
                ) from error

        return _extract_fsm_id(parsed)

    if isinstance(data, dict):
        for key in (
            "data", "fsm_id", "fsmId", "id", "value"
        ):
            if key in data:
                return _extract_fsm_id(data[key])

        raise RuntimeError("Unknown FSM response object")

    if isinstance(data, (list, tuple)):
        for item in data:
            try:
                return _extract_fsm_id(item)
            except RuntimeError:
                continue

    raise RuntimeError("Unsupported FSM response")


def read_fsm() -> int:
    code, data = robot_client._Call(
        FSM_GET_ID_API, "{}"
    )

    if code != 0:
        raise RuntimeError(
            f"GET FSM ID failed: code={code}"
        )

    return _extract_fsm_id(data)


def get_live_status() -> dict:
    with client_lock:
        fsm_id = read_fsm()

    return {
        "connected": True,
        "source": "physical_g1",
        "fsm_id": fsm_id,
        "locomotion_mode": fsm_id == 500,
        "motion_enabled": False,
        "posture_control_available": posture_available(),
        "locomotion_control_available": locomotion_available(),
        "timestamp": utc_now(),
    }


# ============================================================
# EXISTING FSM CONTROL
# ============================================================

def request_control(
    action: str,
    confirmed: bool,
) -> tuple[int, dict]:

    if not isinstance(action, str):
        return 400, {
            "status": "blocked",
            "error": "Invalid action",
        }

    mode = MODES.get(action)

    if mode is None:
        return 400, {
            "status": "blocked",
            "error": "Unsupported control action",
        }

    authorized = (
        posture_available()
        if mode["permission"] == "posture"
        else locomotion_available()
    )

    if not authorized:
        return 403, {
            "status": "blocked",
            "action": action,
            "error": "Requested physical control is not armed",
        }

    if not confirmed:
        return 400, {
            "status": "blocked",
            "action": action,
            "error": "Operator confirmation required",
        }

    if not client_lock.acquire(blocking=False):
        return 409, {
            "status": "busy",
            "action": action,
            "error": "Robot SDK is busy",
        }

    try:
        before = read_fsm()
        expected_source = mode["source"]
        target = mode["target"]

        if before != expected_source:
            return 409, {
                "status": "blocked",
                "action": action,
                "before_fsm": before,
                "expected_fsm": expected_source,
                "target_fsm": target,
                "error": "Unexpected source FSM",
            }

        logger.warning(
            "FSM transition requested: %s -> %s",
            before,
            target,
        )

        code = robot_client.SetFsmId(target)

        if code != 0:
            return 502, {
                "status": "rejected",
                "action": action,
                "sdk_code": code,
                "before_fsm": before,
                "target_fsm": target,
                "error": "SDK rejected FSM transition",
            }

        deadline = time.monotonic() + 8.0
        last_fsm = before

        while time.monotonic() < deadline:
            current = read_fsm()
            last_fsm = current

            if current == target:
                return 200, {
                    "status": "fsm_confirmed",
                    "action": action,
                    "before_fsm": before,
                    "after_fsm": current,
                    "physical_posture_verified": False,
                    "physical_motion_verified": False,
                }

            time.sleep(0.25)

        return 504, {
            "status": "unverified",
            "action": action,
            "before_fsm": before,
            "after_fsm": last_fsm,
            "target_fsm": target,
            "error": "Target FSM was not confirmed",
        }

    except Exception as error:
        logger.exception("Physical control failed")
        return 503, {
            "status": "error",
            "action": action,
            "error": str(error),
        }

    finally:
        client_lock.release()


# ============================================================
# PHYSICAL MOTION CONTROLLER — DRY RUN
# ============================================================

class PhysicalMotionController:

    def __init__(self):
        self.armed = False
        self.velocity = [0.0, 0.0, 0.0]
        self.last_command_time = 0.0
        self.watchdog_triggered = False
        self.stop_requested = False
        self.lock = motion_lock

    def status(self) -> dict:
        with self.lock:
            return {
                "source": "physical_g1",
                "mode": (
                    "physical_dry_run_armed"
                    if self.armed
                    else "physical_disarmed"
                ),
                "physical_motion_enabled": False,
                "armed": self.armed,
                "velocity_commands_available": False,
                "velocity": list(self.velocity),
                "watchdog_timeout_ms": 300,
                "watchdog_triggered": self.watchdog_triggered,
                "stop_requested": self.stop_requested,
                "stop_verified": False,
                "timestamp": utc_now(),
            }

    def arm(self, confirmed: bool) -> tuple[int, dict]:
        if not confirmed:
            return 400, {
                "status": "blocked",
                "error": "Operator confirmation required",
            }

        with self.lock:
            self.armed = True
            self.velocity = [0.0, 0.0, 0.0]
            self.last_command_time = time.monotonic()
            self.watchdog_triggered = False
            self.stop_requested = False

        logger.warning(
            "Dry-run motion controller armed"
        )

        return 200, {
            "status": "armed",
            "mode": "physical_dry_run",
            "physical_motion_enabled": False,
        }

    def move(self, payload: dict) -> tuple[int, dict]:
        try:
            if not isinstance(payload, dict):
                raise ValueError("Invalid motion payload")

            if set(payload) != {"vx", "vy", "omega"}:
                raise ValueError("Unexpected motion fields")

            values = [
                payload["vx"],
                payload["vy"],
                payload["omega"],
            ]

            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in values
            ):
                raise ValueError("Invalid velocity values")

            vx, vy, omega = map(float, values)

        except (ValueError, TypeError, KeyError):
            return 400, {
                "status": "blocked",
                "error": "Invalid velocity request",
            }

        if (
            abs(vx) > MAX_VX
            or abs(vy) > MAX_VY
            or abs(omega) > MAX_OMEGA
        ):
            return 400, {
                "status": "blocked",
                "error": "Velocity exceeds configured limits",
            }

        with self.lock:
            if not self.armed:
                return 403, {
                    "status": "blocked",
                    "error": "Motion controller is disarmed",
                }

            if self.watchdog_triggered:
                return 409, {
                    "status": "blocked",
                    "error": "Watchdog tripped; rearm required",
                }

            self.velocity = [vx, vy, omega]
            self.last_command_time = time.monotonic()
            self.stop_requested = False

            # Dry run only. No SDK velocity call.
            logger.info(
                "DRY RUN velocity: vx=%.3f vy=%.3f omega=%.3f",
                vx, vy, omega,
            )

        return 200, {
            "status": "simulated",
            "mode": "physical_dry_run",
            "velocity": [vx, vy, omega],
            "physical_motion_enabled": False,
        }

    def stop(self) -> tuple[int, dict]:
        with self.lock:
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True

        logger.warning("Dry-run stop requested")

        return 200, {
            "status": "stop_requested",
            "mode": "physical_dry_run",
            "stop_verified": False,
            "physical_motion_enabled": False,
        }

    def physical_stop_test(self) -> tuple[int, dict]:
        # Only invoke while the robot is already stationary, with an
        # independent emergency stop and operator supervision.
        # StopMove returns None, so its return cannot verify stopping.
        with self.lock:
            self.armed = False
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True
        if not client_lock.acquire(blocking=False):
            return 409, {"status": "busy", "error": "SDK busy; stop was not sent", "stop_verified": False}
        try:
            robot_client.StopMove()
            logger.warning("Physical StopMove() sent; verification pending")
            return 200, {
                "status": "physical_stop_sent",
                "physical_motion_enabled": False,
                "stop_verified": False,
                "feedback": motion_feedback.status(),
            }
        except Exception as error:
            logger.exception("Physical stop request failed")
            return 503, {"status": "stop_failed", "error": str(error), "stop_verified": False}
        finally:
            client_lock.release()

    def disarm(self) -> tuple[int, dict]:
        with self.lock:
            self.armed = False
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True

        logger.warning("Motion controller disarmed")

        return 200, {
            "status": "disarmed",
            "physical_motion_enabled": False,
            "stop_verified": False,
        }

    def watchdog_loop(self):
        while True:
            time.sleep(WATCHDOG_INTERVAL)

            with self.lock:
                if not self.armed:
                    continue

                elapsed = (
                    time.monotonic()
                    - self.last_command_time
                )

                if elapsed <= WATCHDOG_TIMEOUT:
                    continue

                self.velocity = [0.0, 0.0, 0.0]
                self.armed = False
                self.watchdog_triggered = True
                self.stop_requested = True

                logger.warning(
                    "DRY RUN watchdog timeout: %.3f seconds",
                    elapsed,
                )


motion_controller = PhysicalMotionController()


def get_physical_motion_status() -> dict:
    with client_lock:
        fsm_id = read_fsm()

    result = motion_controller.status()
    result.update({
        "connected": True,
        "fsm_id": fsm_id,
        "locomotion_mode": fsm_id == 500,
        "feedback": motion_feedback.status(),
    })

    return result


# ============================================================
# HTTP BRIDGE
# ============================================================

class Handler(BaseHTTPRequestHandler):

    def respond(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type", "application/json"
        )
        self.send_header(
            "Cache-Control", "no-store"
        )
        self.send_header(
            "Content-Length", str(len(body))
        )
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        supplied = self.headers.get(
            "X-G1-Bridge-Token", ""
        )

        return bool(CONTROL_TOKEN) and hmac.compare_digest(
            supplied, CONTROL_TOKEN
        )

    def read_payload(self) -> dict:
        length = int(
            self.headers.get("Content-Length", "0")
        )

        if length <= 0 or length > 1024:
            raise ValueError("Invalid request size")

        payload = json.loads(
            self.rfile.read(length)
        )

        if not isinstance(payload, dict):
            raise ValueError("Invalid JSON payload")

        return payload

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {
                "status": "ok",
                "service": "g1-status-bridge",
                "posture_control_available": posture_available(),
                "locomotion_control_available": locomotion_available(),
                "physical_motion_enabled": False,
                "motion_controller": "dry_run",
            })
            return

        if self.path not in (
            "/status",
            "/physical-motion/status",
        ):
            self.respond(404, {
                "error": "Not found"
            })
            return

        try:
            if self.path == "/status":
                payload = get_live_status()
            else:
                payload = get_physical_motion_status()

            self.respond(200, payload)

        except Exception as error:
            logger.exception("Status request failed")
            self.respond(503, {
                "connected": False,
                "source": "physical_g1",
                "physical_motion_enabled": False,
                "armed": False,
                "error": str(error),
            })

    def do_POST(self):
        routes = (
            "/posture",
            "/physical-motion/arm",
            "/physical-motion",
            "/physical-motion/stop",
            "/physical-motion/disarm",
            "/physical-motion/physical-stop-test",
        )

        if self.path not in routes:
            self.respond(404, {
                "error": "Not found"
            })
            return

        if not self.authorized():
            self.respond(403, {
                "error": "Unauthorized control request"
            })
            return

        try:
            if self.path == "/physical-motion/physical-stop-test":
                code, result = motion_controller.physical_stop_test()

            elif self.path == "/physical-motion/stop":
                code, result = motion_controller.stop()

            elif self.path == "/physical-motion/disarm":
                code, result = motion_controller.disarm()

            else:
                payload = self.read_payload()

                if self.path == "/posture":
                    code, result = request_control(
                        payload.get("action"),
                        payload.get("confirmed") is True,
                    )

                elif self.path == "/physical-motion/arm":
                    code, result = motion_controller.arm(
                        payload.get("confirmed") is True
                    )

                elif self.path == "/physical-motion":
                    code, result = motion_controller.move(
                        payload
                    )

            self.respond(code, result)

        except (ValueError, TypeError, KeyError):
            self.respond(400, {
                "error": "Invalid request"
            })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    motion_feedback.start()

    watchdog_thread = threading.Thread(
        target=motion_controller.watchdog_loop,
        daemon=True,
        name="g1-motion-watchdog",
    )

    watchdog_thread.start()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    logger.info(
        "G1 bridge listening on %s:%s",
        HOST,
        PORT,
    )

    logger.info(
        "Posture commands armed: %s",
        posture_available(),
    )

    logger.info(
        "Locomotion FSM commands armed: %s",
        locomotion_available(),
    )

    logger.info(
        "Physical velocity output: DISABLED"
    )

    logger.info(
        "Motion controller: DRY RUN"
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()