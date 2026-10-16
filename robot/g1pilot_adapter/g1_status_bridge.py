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
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
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
PHYSICAL_MOTION_ENABLED = os.getenv("G1_ENABLE_PHYSICAL_PULSE") == "1"

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
    """Read-only G1 LowState feedback; NOT translational velocity feedback."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last_received = None
        self.yaw_speed = None
        self.gyroscope = None
        self.accelerometer = None
        self.message_count = 0
        self.subscriber = None
        self.error = None

    def callback(self, message):
        try:
            gyro = [float(v) for v in message.imu_state.gyroscope]
            accel = [float(v) for v in message.imu_state.accelerometer]
            if len(gyro) != 3 or len(accel) != 3:
                return
            if not all(math.isfinite(v) for v in gyro + accel):
                return
            with self.lock:
                self.gyroscope = gyro
                self.accelerometer = accel
                self.yaw_speed = gyro[2]
                self.last_received = time.monotonic()
                self.message_count += 1
                self.error = None
        except Exception:
            logger.exception("Invalid G1 LowState feedback")

    def start(self):
        try:
            self.subscriber = ChannelSubscriber("rt/lowstate", LowState_)
            self.subscriber.Init(self.callback, 10)
            logger.info("G1 LowState feedback subscriber started")
        except Exception as error:
            with self.lock:
                self.error = str(error)
            logger.exception("G1 LowState feedback unavailable")

    def status(self):
        with self.lock:
            age = None if self.last_received is None else time.monotonic() - self.last_received
            return {
                "feedback_source": "rt/lowstate",
                "feedback_received": self.last_received is not None,
                "feedback_fresh": age is not None and age <= 0.5,
                "feedback_age_ms": None if age is None else round(age * 1000),
                "feedback_message_count": self.message_count,
                "measured_velocity": None,
                "measured_yaw_speed": self.yaw_speed,
                "imu_gyroscope": None if self.gyroscope is None else list(self.gyroscope),
                "imu_accelerometer": None if self.accelerometer is None else list(self.accelerometer),
                "translation_velocity_available": False,
                "stop_verified_by_feedback": False,
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
        "motion_enabled": False,  # Physical continuous velocity commands are not authorized.
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
        self.last_stop_error = None
        self.last_stop_sent = False
        self.lock = motion_lock
        self.command_lock = threading.RLock()
        self.command_generation = 0
        self.pulse_active = False
        self.fault_latched = False
        self.stop_event = threading.Event()
        self.last_stop_rpc_elapsed_ms = None
        self.last_stop_reason = None
        self.watchdog_last_elapsed_ms = None
        self.watchdog_stop_attempted = False

    def status(self) -> dict:
        with self.lock:
            return {
                "source": "physical_g1",
                "mode": (
                    "physical_dry_run_armed"
                    if self.armed
                    else "physical_disarmed"
                ),
                "physical_motion_enabled": PHYSICAL_MOTION_ENABLED,
                "pulse_active": self.pulse_active,
                "fault_latched": self.fault_latched,
                "armed": self.armed,
                "velocity_commands_available": False,
                "velocity": list(self.velocity),
                "watchdog_timeout_ms": round(WATCHDOG_TIMEOUT * 1000),
                "watchdog_triggered": self.watchdog_triggered,
                "stop_requested": self.stop_requested,
                "stop_verified": False,
                "last_stop_sent": self.last_stop_sent,
                "last_stop_error": self.last_stop_error,
                "last_stop_reason": self.last_stop_reason,
                "last_stop_rpc_elapsed_ms": self.last_stop_rpc_elapsed_ms,
                "watchdog_last_elapsed_ms": self.watchdog_last_elapsed_ms,
                "watchdog_stop_attempted": self.watchdog_stop_attempted,
                "stop_verification_reason": "No independently measured translational velocity; SDK acknowledgment is not physical stop verification",
                "command_generation": self.command_generation,
                "timestamp": utc_now(),
            }

    def arm(self, confirmed: bool) -> tuple[int, dict]:
        if not confirmed:
            return 400, {
                "status": "blocked",
                "error": "Operator confirmation required",
            }

        with self.command_lock, self.lock:
            if self.fault_latched:
                return 409, {"status": "blocked", "error": "Fault latched; restart bridge after operator inspection"}
            if self.pulse_active:
                return 409, {"status": "blocked", "error": "Pulse active"}
            self.stop_event.clear()
            self.command_generation += 1
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

        with self.command_lock, self.lock:
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

            self.command_generation += 1
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

    def _send_sdk_stop(self, reason: str) -> tuple[int, dict]:
        """Best-effort SDK zero-motion request; not proof of physical stopping."""
        started = time.monotonic()
        with self.lock:
            self.last_stop_reason = reason
            self.last_stop_rpc_elapsed_ms = None
        acquired = client_lock.acquire(timeout=1.0)
        if not acquired:
            error = "SDK busy; zero-velocity stop was not sent"
            with self.lock:
                self.last_stop_sent = False
                self.last_stop_error = error
                self.last_stop_rpc_elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            logger.error("%s: %s", reason, error)
            return 503, {
                "status": "stop_failed", "error": error,
                "stop_verified": False, "physical_motion_enabled": False,
            }
        try:
            # StopMove() discards the SDK response code. Use its equivalent
            # zero-velocity request directly so RPC errors are observable.
            sdk_code = robot_client.SetVelocity(0.0, 0.0, 0.0, duration=1.0)
            with self.lock:
                self.last_stop_rpc_elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            if sdk_code != 0:
                error = f"Zero-velocity SDK request returned code {sdk_code}"
                with self.lock:
                    self.last_stop_sent = False
                    self.last_stop_error = error
                logger.error("Stop request failed (%s): %s", reason, error)
                return 503, {
                    "status": "stop_failed",
                    "reason": reason,
                    "sdk_code": sdk_code,
                    "error": error,
                    "stop_verified": False,
                    "physical_motion_enabled": False,
                }
            with self.lock:
                self.last_stop_sent = True
                self.last_stop_error = None
            logger.warning("Zero-velocity SDK request acknowledged (%s); physical stop unverified", reason)
            return 200, {
                "status": "stop_acknowledged",
                "reason": reason,
                "sdk_code": sdk_code,
                "stop_verified": False,
                "physical_motion_enabled": PHYSICAL_MOTION_ENABLED,
                "feedback": motion_feedback.status(),
            }
        except Exception as error:
            logger.exception("StopMove() failed (%s)", reason)
            with self.lock:
                self.last_stop_sent = False
                self.last_stop_error = str(error)
                self.last_stop_rpc_elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            return 503, {
                "status": "stop_failed", "error": str(error),
                "stop_verified": False, "physical_motion_enabled": False,
            }
        finally:
            client_lock.release()

    def stop(self) -> tuple[int, dict]:
        self.stop_event.set()
        with self.lock:
            self.command_generation += 1
            self.armed = False
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True
            self.fault_latched = self.fault_latched or self.pulse_active
        return self._send_sdk_stop("operator_stop")

    def physical_stop_test(self) -> tuple[int, dict]:
        self.stop_event.set()
        # Stationary test only; StopMove() returning does not verify motion.
        with self.lock:
            self.command_generation += 1
            self.armed = False
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True
            self.fault_latched = self.fault_latched or self.pulse_active
        return self._send_sdk_stop("stationary_stop_test")

    def disarm(self) -> tuple[int, dict]:
        self.stop_event.set()
        with self.lock:
            self.command_generation += 1
            self.armed = False
            self.velocity = [0.0, 0.0, 0.0]
            self.stop_requested = True
            self.fault_latched = self.fault_latched or self.pulse_active
        return self._send_sdk_stop("disarm")

    def test_pulse(self, confirmed: bool) -> tuple[int, dict]:
        """Single 150 ms dry-run pulse; intentionally no nonzero SDK call."""
        if not confirmed:
            return 400, {"status": "blocked", "error": "Operator confirmation required"}
        with self.command_lock:
            with self.lock:
                if not self.armed or self.watchdog_triggered:
                    return 409, {"status": "blocked", "error": "Arm dry-run controller first"}
            feedback = motion_feedback.status()
            if not feedback["feedback_fresh"]:
                return 503, {"status": "blocked", "error": "Stale LowState feedback"}
            with client_lock:
                fsm = read_fsm()
            if fsm != 500:
                return 409, {"status": "blocked", "error": f"FSM {fsm} is not locomotion mode"}
            with self.lock:
                self.command_generation += 1
                self.velocity = [0.03, 0.0, 0.0]
                self.last_command_time = time.monotonic()
                generation = self.command_generation
            logger.warning("DRY RUN test pulse generation=%s vx=0.03 for 150ms", generation)
            time.sleep(0.150)
            with self.lock:
                self.command_generation += 1
                self.velocity = [0.0, 0.0, 0.0]
                self.armed = False
                self.stop_requested = True
            stop_code, stop_result = self._send_sdk_stop("dry_run_pulse_completed")
            return stop_code, {
                "status": "dry_run_pulse_completed" if stop_code == 200 else "stop_failed",
                "nonzero_sdk_velocity_sent": False,
                "simulated_velocity": [0.03, 0.0, 0.0],
                "simulated_duration_ms": 150,
                "stop": stop_result,
                "physical_motion_enabled": False,
            }

    def physical_pulse(self, confirmed: bool) -> tuple[int, dict]:
        """One short forward SDK command, opt-in only; no continuous mode.

        The stop RPC acknowledgment does not prove physical stopping.
        Hardware emergency stop and human supervision remain necessary.
        """
        if not PHYSICAL_MOTION_ENABLED:
            return 403, {"status": "blocked", "error": "Physical pulse gate disabled"}
        if not confirmed:
            return 400, {"status": "blocked", "error": "Operator confirmation required"}
        if not self.command_lock.acquire(blocking=False):
            return 409, {"status": "blocked", "error": "Another command is active"}
        sent = False
        result = None
        stop_code = 503
        stop_result = {"status": "stop_not_attempted"}
        try:
            with self.lock:
                if self.fault_latched or self.pulse_active:
                    return 409, {"status": "blocked", "error": "Motion fault or active pulse"}
                if not self.armed or self.watchdog_triggered or self.stop_event.is_set():
                    return 409, {"status": "blocked", "error": "Arm controller immediately before pulse"}
            if not motion_feedback.status()["feedback_fresh"]:
                return 503, {"status": "blocked", "error": "Stale LowState feedback"}
            if not client_lock.acquire(timeout=0.2):
                return 503, {"status": "blocked", "error": "SDK busy"}
            try:
                fsm = read_fsm()
                if fsm != 500:
                    return 409, {"status": "blocked", "error": f"FSM {fsm} != 500"}
                if self.stop_event.is_set() or not motion_feedback.status()["feedback_fresh"]:
                    return 409, {"status": "blocked", "error": "Stop requested or feedback stale"}
                with self.lock:
                    self.pulse_active = True
                    self.command_generation += 1
                    self.velocity = [0.03, 0.0, 0.0]
                    self.last_command_time = time.monotonic()
                # Last cancellation check before issuing the SDK request.
                # A concurrent stop can still race after this check; the
                # independent physical E-stop remains mandatory.
                if self.stop_event.is_set():
                    result = {"status": "cancelled_before_send"}
                else:
                    sent = True  # Outcome uncertain if RPC times out.
                    logger.warning("PHYSICAL PULSE requested vx=0.03 duration=0.15 seconds")
                    rpc_started = time.monotonic()
                    code = robot_client.SetVelocity(0.03, 0.0, 0.0, duration=0.15)
                    rpc_elapsed_ms = round((time.monotonic() - rpc_started) * 1000, 2)
                    logger.warning("PHYSICAL PULSE SDK RPC elapsed_ms=%s code=%s", rpc_elapsed_ms, code)
                    if code != 0:
                        result = {"status": "motion_sdk_error", "sdk_code": code, "rpc_elapsed_ms": rpc_elapsed_ms}
                    else:
                        result = {"status": "motion_acknowledged", "sdk_code": code, "rpc_elapsed_ms": rpc_elapsed_ms}
            except Exception as exc:
                result = {"status": "motion_outcome_uncertain", "error": str(exc)}
                logger.exception("Physical pulse RPC failed; operator intervention may be required")
            finally:
                client_lock.release()
            # Request stop immediately after the SDK call. Do not sleep while moving.
            # If the RPC blocks, the independent physical E-stop is essential.
            stop_started = time.monotonic()
            stop_code, stop_result = self._send_sdk_stop("physical_pulse_end")
            stop_elapsed_ms = round((time.monotonic() - stop_started) * 1000, 2)
            logger.warning("PHYSICAL PULSE stop RPC elapsed_ms=%s http_code=%s", stop_elapsed_ms, stop_code)
            if stop_code != 200 or result["status"] != "motion_acknowledged" or self.stop_event.is_set():
                logger.error("Physical pulse fault; use physical E-stop if robot moves")
            return (200 if stop_code == 200 and result["status"] == "motion_acknowledged" and not self.stop_event.is_set() else 503), {
                "status": "physical_pulse_completed_unverified" if stop_code == 200 and result["status"] == "motion_acknowledged" and not self.stop_event.is_set() else "physical_pulse_fault",
                "nonzero_sdk_velocity_sent_or_attempted": sent,
                "requested_velocity": [0.03, 0.0, 0.0],
                "requested_duration_ms": 150,
                "motion": result,
                "stop": stop_result,
                "stop_rpc_elapsed_ms": stop_elapsed_ms,
                "stop_verified": False,
                "operator_must_confirm_stationary": True,
            }
        finally:
            with self.lock:
                if sent:
                    self.fault_latched = True  # No second pulse until operator inspects and bridge restarts.
                self.pulse_active = False
                self.armed = False
                self.velocity = [0.0, 0.0, 0.0]
                self.stop_requested = True
                self.command_generation += 1
            self.command_lock.release()

    def watchdog_loop(self):
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            with self.lock:
                if not self.armed:
                    continue
                elapsed = time.monotonic() - self.last_command_time
                if elapsed <= WATCHDOG_TIMEOUT:
                    continue
                # Signal cancellation before waiting for the SDK client.
                # This thread must never wait for command_lock.
                self.stop_event.set()
                self.command_generation += 1
                self.velocity = [0.0, 0.0, 0.0]
                self.armed = False
                self.watchdog_triggered = True
                self.watchdog_last_elapsed_ms = round(elapsed * 1000, 2)
                self.watchdog_stop_attempted = True
                self.stop_requested = True
                self.fault_latched = self.fault_latched or self.pulse_active
            logger.warning("Watchdog timeout: %.3f seconds", elapsed)
            # Best effort only: SDK client_lock may still be held by a timed-out RPC.
            self._send_sdk_stop("watchdog_timeout")


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
                "physical_motion_enabled": PHYSICAL_MOTION_ENABLED,
                "motion_controller": "bounded_physical_pulse" if PHYSICAL_MOTION_ENABLED else "dry_run",
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
            "/physical-motion/test-pulse",
            "/physical-motion/physical-pulse",
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

                elif self.path == "/physical-motion/physical-pulse":
                    code, result = motion_controller.physical_pulse(
                        payload.get("confirmed") is True
                    )

                elif self.path == "/physical-motion/test-pulse":
                    code, result = motion_controller.test_pulse(
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
        "Physical pulse output enabled: %s", PHYSICAL_MOTION_ENABLED
    )

    logger.info(
        "Motion controller: guarded single pulse / dry run"
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()