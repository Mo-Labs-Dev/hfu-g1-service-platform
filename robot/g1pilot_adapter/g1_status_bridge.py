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

from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize,
    ChannelSubscriber,
)
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "127.0.0.1"
PORT = 8767
INTERFACE = "enP2p1s0"

FSM_GET_ID_API = 7001

CONTROL_TOKEN = os.getenv("G1_BRIDGE_TOKEN", "")

ALLOW_POSTURE_COMMANDS = (
    os.getenv("G1_ALLOW_POSTURE_COMMANDS") == "1"
)

ALLOW_LOCOMOTION_COMMANDS = (
    os.getenv("G1_ALLOW_LOCOMOTION_COMMANDS") == "1"
)

MAX_VX = 0.05
MAX_VY = 0.05
MAX_OMEGA = 0.10

WATCHDOG_TIMEOUT = 0.300
WATCHDOG_INTERVAL = 0.025

# Continuous physical walking is intentionally locked.
# Do not enable it using an environment variable alone.
PHYSICAL_MOTION_ENABLED = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("g1-status-bridge")

client_lock = threading.Lock()
motion_lock = threading.RLock()


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def posture_available() -> bool:
    return (
        ALLOW_POSTURE_COMMANDS
        and bool(CONTROL_TOKEN)
    )


def locomotion_available() -> bool:
    return (
        ALLOW_LOCOMOTION_COMMANDS
        and bool(CONTROL_TOKEN)
    )


# ============================================================
# UNITREE SDK
# ============================================================

def create_client() -> LocoClient:
    ChannelFactoryInitialize(0, INTERFACE)

    client = LocoClient()
    client.SetTimeout(3.0)
    client.Init()

    return client


robot_client = create_client()


# ============================================================
# LIVE LOWSTATE FEEDBACK
# ============================================================

class LiveMotionFeedback:

    def __init__(self):
        self.lock = threading.Lock()
        self.last_received = None
        self.message_count = 0
        self.gyroscope = None
        self.accelerometer = None
        self.error = None
        self.subscriber = None

    def callback(self, message):
        try:
            gyro = [
                float(value)
                for value in message.imu_state.gyroscope
            ]

            accel = [
                float(value)
                for value in message.imu_state.accelerometer
            ]

            if len(gyro) != 3 or len(accel) != 3:
                return

            if not all(
                math.isfinite(value)
                for value in gyro + accel
            ):
                return

            with self.lock:
                self.gyroscope = gyro
                self.accelerometer = accel
                self.last_received = time.monotonic()
                self.message_count += 1
                self.error = None

        except Exception:
            logger.exception("Invalid LowState feedback")

    def start(self):
        try:
            self.subscriber = ChannelSubscriber(
                "rt/lowstate",
                LowState_,
            )

            self.subscriber.Init(self.callback, 10)

            logger.info("LowState subscriber started")

        except Exception as error:
            with self.lock:
                self.error = str(error)

            logger.exception(
                "LowState subscriber failed"
            )

    def status(self) -> dict:
        with self.lock:
            age = (
                None
                if self.last_received is None
                else time.monotonic() - self.last_received
            )

            return {
                "feedback_source": "rt/lowstate",
                "feedback_received": (
                    self.last_received is not None
                ),
                "feedback_fresh": (
                    age is not None and age <= 0.5
                ),
                "feedback_age_ms": (
                    None
                    if age is None
                    else round(age * 1000)
                ),
                "feedback_message_count": (
                    self.message_count
                ),
                "measured_velocity": None,
                "measured_yaw_speed": (
                    None
                    if self.gyroscope is None
                    else self.gyroscope[2]
                ),
                "imu_gyroscope": (
                    None
                    if self.gyroscope is None
                    else list(self.gyroscope)
                ),
                "imu_accelerometer": (
                    None
                    if self.accelerometer is None
                    else list(self.accelerometer)
                ),
                "translation_velocity_available": False,
                "stop_verified_by_feedback": False,
                "feedback_error": self.error,
            }


motion_feedback = LiveMotionFeedback()


# ============================================================
# FSM READING
# ============================================================

def extract_fsm_id(data) -> int:
    if data is None or isinstance(data, bool):
        raise RuntimeError("Invalid FSM response")

    if isinstance(data, (int, float)):
        return int(data)

    if isinstance(data, bytes):
        data = data.decode("utf-8")

    if isinstance(data, str):
        value = data.strip()

        try:
            return extract_fsm_id(json.loads(value))
        except json.JSONDecodeError:
            return int(value)

    if isinstance(data, dict):
        for key in (
            "data",
            "fsm_id",
            "fsmId",
            "id",
            "value",
        ):
            if key in data:
                return extract_fsm_id(data[key])

    if isinstance(data, (list, tuple)):
        for item in data:
            try:
                return extract_fsm_id(item)
            except (ValueError, RuntimeError, TypeError):
                continue

    raise RuntimeError("Unable to extract FSM ID")


def read_fsm() -> int:
    code, data = robot_client._Call(
        FSM_GET_ID_API,
        "{}",
    )

    if code != 0:
        raise RuntimeError(
            f"FSM request failed: {code}"
        )

    return extract_fsm_id(data)


def get_live_status() -> dict:
    with client_lock:
        fsm = read_fsm()

    return {
        "connected": True,
        "source": "physical_g1",
        "fsm_id": fsm,
        "locomotion_mode": fsm == 500,
        "motion_enabled": False,
        "posture_control_available": posture_available(),
        "locomotion_control_available": locomotion_available(),
        "timestamp": utc_now(),
    }


# ============================================================
# FSM CONTROL
# ============================================================

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


def request_control(
    action: str,
    confirmed: bool,
) -> tuple[int, dict]:

    mode = MODES.get(action)

    if mode is None:
        return 400, {
            "status": "blocked",
            "error": "Unsupported FSM action",
        }

    if not confirmed:
        return 400, {
            "status": "blocked",
            "error": "Operator confirmation required",
        }

    authorized = (
        posture_available()
        if mode["permission"] == "posture"
        else locomotion_available()
    )

    if not authorized:
        return 403, {
            "status": "blocked",
            "error": "FSM command disabled",
        }

    if not client_lock.acquire(blocking=False):
        return 409, {
            "status": "busy",
            "error": "Robot SDK busy",
        }

    try:
        before = read_fsm()

        if before != mode["source"]:
            return 409, {
                "status": "blocked",
                "before_fsm": before,
                "expected_fsm": mode["source"],
                "target_fsm": mode["target"],
                "error": "Unexpected source FSM",
            }

        code = robot_client.SetFsmId(
            mode["target"]
        )

        if code != 0:
            return 502, {
                "status": "rejected",
                "sdk_code": code,
                "error": "FSM transition rejected",
            }

        deadline = time.monotonic() + 8.0
        last_fsm = before

        while time.monotonic() < deadline:
            last_fsm = read_fsm()

            if last_fsm == mode["target"]:
                return 200, {
                    "status": "fsm_confirmed",
                    "action": action,
                    "before_fsm": before,
                    "after_fsm": last_fsm,
                    "physical_posture_verified": False,
                    "physical_motion_verified": False,
                }

            time.sleep(0.25)

        return 504, {
            "status": "unverified",
            "action": action,
            "before_fsm": before,
            "after_fsm": last_fsm,
            "error": "FSM transition timed out",
        }

    except Exception as error:
        logger.exception("FSM control failed")

        return 503, {
            "status": "error",
            "action": action,
            "error": str(error),
        }

    finally:
        client_lock.release()


# ============================================================
# PHYSICAL MOTION CONTROLLER
# ============================================================

class PhysicalMotionController:

    def __init__(self):
        self.lock = motion_lock
        self.armed = False
        self.velocity = [0.0, 0.0, 0.0]
        self.last_command_time = 0.0
        self.command_generation = 0

        self.stop_requested = False
        self.stop_event = threading.Event()

        self.watchdog_triggered = False
        self.watchdog_last_elapsed_ms = None
        self.watchdog_stop_attempted = False

        self.fault_latched = False
        self.pulse_active = False

        self.last_stop_sent = False
        self.last_stop_error = None
        self.last_stop_reason = None
        self.last_stop_rpc_elapsed_ms = None

    def status(self) -> dict:
        with self.lock:
            return {
                "source": "physical_g1",
                "mode": "physical_disarmed",
                "physical_motion_enabled": False,
                "pulse_active": False,
                "fault_latched": self.fault_latched,
                "armed": False,
                "velocity_commands_available": False,
                "velocity": [0.0, 0.0, 0.0],
                "watchdog_timeout_ms": round(
                    WATCHDOG_TIMEOUT * 1000
                ),
                "watchdog_triggered": (
                    self.watchdog_triggered
                ),
                "stop_requested": self.stop_requested,
                "stop_verified": False,
                "last_stop_sent": self.last_stop_sent,
                "last_stop_error": self.last_stop_error,
                "last_stop_reason": self.last_stop_reason,
                "last_stop_rpc_elapsed_ms": (
                    self.last_stop_rpc_elapsed_ms
                ),
                "watchdog_last_elapsed_ms": (
                    self.watchdog_last_elapsed_ms
                ),
                "watchdog_stop_attempted": (
                    self.watchdog_stop_attempted
                ),
                "stop_verification_reason": (
                    "Independent translational velocity "
                    "feedback is unavailable"
                ),
                "command_generation": (
                    self.command_generation
                ),
                "timestamp": utc_now(),
            }

    def arm(
        self,
        confirmed: bool,
    ) -> tuple[int, dict]:

        return 403, {
            "status": "blocked",
            "error": (
                "Continuous physical motion cannot be "
                "armed until independent stopping is verified"
            ),
            "physical_motion_enabled": False,
        }

    def move(
        self,
        payload: dict,
    ) -> tuple[int, dict]:

        return 403, {
            "status": "blocked",
            "error": (
                "Continuous physical velocity commands "
                "are not safety-authorized"
            ),
            "physical_motion_enabled": False,
        }

    def _send_sdk_stop(
        self,
        reason: str,
    ) -> tuple[int, dict]:

        started = time.monotonic()

        with self.lock:
            self.armed = False
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True
            self.stop_event.set()
            self.command_generation += 1

            self.last_stop_reason = reason
            self.last_stop_sent = False
            self.last_stop_error = None
            self.last_stop_rpc_elapsed_ms = None

        acquired = client_lock.acquire(
            timeout=1.0
        )

        if not acquired:
            error = (
                "SDK busy; zero-velocity stop "
                "could not be sent"
            )

            with self.lock:
                self.last_stop_error = error
                self.fault_latched = True
                self.last_stop_rpc_elapsed_ms = round(
                    (time.monotonic() - started) * 1000,
                    2,
                )

            logger.error("%s: %s", reason, error)

            return 503, {
                "status": "stop_failed",
                "error": error,
                "stop_verified": False,
                "physical_motion_enabled": False,
            }

        try:
            code = robot_client.SetVelocity(
                0.0,
                0.0,
                0.0,
                duration=1.0,
            )

            elapsed_ms = round(
                (time.monotonic() - started) * 1000,
                2,
            )

            with self.lock:
                self.last_stop_rpc_elapsed_ms = elapsed_ms

            if code != 0:
                error = (
                    f"SDK stop returned code {code}"
                )

                with self.lock:
                    self.last_stop_error = error
                    self.fault_latched = True

                return 503, {
                    "status": "stop_failed",
                    "sdk_code": code,
                    "error": error,
                    "stop_verified": False,
                    "physical_motion_enabled": False,
                }

            with self.lock:
                self.last_stop_sent = True
                self.last_stop_error = None

            logger.warning(
                "Stop acknowledged: %s, %.2f ms",
                reason,
                elapsed_ms,
            )

            return 200, {
                "status": "stop_acknowledged",
                "reason": reason,
                "sdk_code": code,
                "stop_verified": False,
                "physical_motion_enabled": False,
                "stop_rpc_elapsed_ms": elapsed_ms,
                "feedback": motion_feedback.status(),
            }

        except Exception as error:
            logger.exception(
                "Physical stop failed"
            )

            with self.lock:
                self.last_stop_error = str(error)
                self.fault_latched = True

            return 503, {
                "status": "stop_failed",
                "error": str(error),
                "stop_verified": False,
                "physical_motion_enabled": False,
            }

        finally:
            client_lock.release()

    def stop(self) -> tuple[int, dict]:
        return self._send_sdk_stop(
            "operator_stop"
        )

    def disarm(self) -> tuple[int, dict]:
        return self._send_sdk_stop(
            "operator_disarm"
        )

    def physical_stop_test(
        self,
    ) -> tuple[int, dict]:
        return self._send_sdk_stop(
            "stationary_stop_test"
        )

    def test_pulse(
        self,
        confirmed: bool,
    ) -> tuple[int, dict]:

        return 403, {
            "status": "blocked",
            "error": (
                "Pulse testing disabled in this "
                "stop-safety preparation build"
            ),
        }

    def physical_pulse(
        self,
        confirmed: bool,
    ) -> tuple[int, dict]:

        return 403, {
            "status": "blocked",
            "error": (
                "Physical pulse disabled in this "
                "stop-safety preparation build"
            ),
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

                self.armed = False
                self.velocity = [0.0, 0.0, 0.0]
                self.stop_event.set()

                self.watchdog_triggered = True
                self.watchdog_stop_attempted = True
                self.watchdog_last_elapsed_ms = round(
                    elapsed * 1000,
                    2,
                )
                self.fault_latched = True

            logger.error(
                "Physical motion watchdog triggered"
            )

            self._send_sdk_stop(
                "watchdog_timeout"
            )


motion_controller = PhysicalMotionController()


# ============================================================
# PHYSICAL STATUS
# ============================================================

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
# HTTP SERVER
# ============================================================

class Handler(BaseHTTPRequestHandler):

    def respond(
        self,
        status: int,
        payload: dict,
    ):
        body = json.dumps(payload).encode(
            "utf-8"
        )

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        supplied = self.headers.get(
            "X-G1-Bridge-Token",
            "",
        )

        return (
            bool(CONTROL_TOKEN)
            and hmac.compare_digest(
                supplied,
                CONTROL_TOKEN,
            )
        )

    def read_payload(self) -> dict:
        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        if length <= 0 or length > 1024:
            raise ValueError(
                "Invalid request size"
            )

        payload = json.loads(
            self.rfile.read(length)
        )

        if not isinstance(payload, dict):
            raise ValueError(
                "Invalid JSON payload"
            )

        return payload

    def do_GET(self):

        if self.path == "/health":
            self.respond(200, {
                "status": "ok",
                "service": "g1-status-bridge",
                "posture_control_available": (
                    posture_available()
                ),
                "locomotion_control_available": (
                    locomotion_available()
                ),
                "physical_motion_enabled": False,
                "motion_controller": "safety_locked",
            })
            return

        try:
            if self.path == "/status":
                self.respond(
                    200,
                    get_live_status(),
                )
                return

            if self.path == "/physical-motion/status":
                self.respond(
                    200,
                    get_physical_motion_status(),
                )
                return

            self.respond(
                404,
                {"error": "Not found"},
            )

        except Exception as error:
            logger.exception(
                "GET request failed"
            )

            self.respond(503, {
                "connected": False,
                "source": "physical_g1",
                "error": str(error),
            })

    def do_POST(self):

        routes = {
            "/posture",
            "/physical-motion/arm",
            "/physical-motion",
            "/physical-motion/stop",
            "/physical-motion/disarm",
            "/physical-motion/physical-stop-test",
            "/physical-motion/test-pulse",
            "/physical-motion/physical-pulse",
        }

        if self.path not in routes:
            self.respond(
                404,
                {"error": "Not found"},
            )
            return

        if not self.authorized():
            self.respond(
                403,
                {"error": "Unauthorized control request"},
            )
            return

        try:
            if self.path == "/physical-motion/stop":
                code, result = motion_controller.stop()

            elif self.path == "/physical-motion/disarm":
                code, result = motion_controller.disarm()

            elif self.path == (
                "/physical-motion/physical-stop-test"
            ):
                code, result = (
                    motion_controller.physical_stop_test()
                )

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

                elif self.path == (
                    "/physical-motion/test-pulse"
                ):
                    code, result = (
                        motion_controller.test_pulse(
                            payload.get("confirmed") is True
                        )
                    )

                elif self.path == (
                    "/physical-motion/physical-pulse"
                ):
                    code, result = (
                        motion_controller.physical_pulse(
                            payload.get("confirmed") is True
                        )
                    )

            self.respond(code, result)

        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            self.respond(
                400,
                {"error": "Invalid request"},
            )

        except Exception as error:
            logger.exception(
                "POST request failed"
            )

            self.respond(
                503,
                {"error": str(error)},
            )


# ============================================================
# MAIN
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
        "Posture control available: %s",
        posture_available(),
    )

    logger.info(
        "Locomotion FSM available: %s",
        locomotion_available(),
    )

    logger.info(
        "Continuous physical motion: LOCKED"
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()