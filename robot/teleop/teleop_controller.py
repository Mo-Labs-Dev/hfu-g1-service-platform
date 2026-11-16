from __future__ import annotations

import hmac
import math
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable

from robot.teleop.motion_backends import (
    ARM_RELEASE,
    FSM_DAMP,
    FSM_LOCOMOTION,
    FSM_STAND_UP,
    MotionBackend,
)

# Operator-selectable robot modes and the FSM each one requests.
# ZeroTorque (FSM 0) is deliberately NOT offered: the robot would fall.
MODE_TARGETS = {
    "damp": FSM_DAMP,
    "stand_up": FSM_STAND_UP,
    "walk": FSM_LOCOMOTION,
}
# Arm gestures (G1 Arm Action Service ids, see official action_map).
GESTURES: dict[str, tuple[int, str]] = {
    "high_wave": (26, "Wave"),
    "face_wave": (25, "Wave (chest)"),
    "clap": (17, "Clap"),
    "heart": (20, "Heart"),
    "right_heart": (21, "Heart (one hand)"),
    "high_five": (18, "High five"),
    "shake_hand": (27, "Shake hand"),
    "hug": (19, "Hug"),
    "two_hand_kiss": (11, "Flying kiss"),
    "hands_up": (15, "Arms out"),
    "release_arm": (ARM_RELEASE, "Arms down"),
}
# Subset visitors may trigger in demo mode: no contact gestures
# (hug / handshake / high five invite people to step close to the robot).
VISITOR_GESTURES = ("high_wave", "face_wave", "clap", "heart", "two_hand_kiss")
# By voice the person asking is standing in front of the robot and wants
# contact, so handshake and high five are allowed. Hug stays excluded.
VOICE_GESTURES = VISITOR_GESTURES + ("shake_hand", "high_five")

# Gestures that stay in their final pose and must be released (id 99).
SUSTAINED_GESTURES = {15, 18, 20, 21, 22, 23, 27}
HANDSHAKE_ID = 27
ARM_ERRORS = {
    7400: "Another arm action is still running.",
    7401: "Arms were still raised - they were lowered, please try again.",
    7402: "This gesture is not available on this robot firmware.",
    7404: "This gesture is not allowed in the current robot mode.",
}

# Required current FSM for each transition (damp is always allowed).
MODE_ALLOWED_FROM = {
    "stand_up": {FSM_DAMP},
    "walk": {FSM_STAND_UP},
}


@dataclass(frozen=True)
class TeleopLimits:
    # Speeds reached at full stick deflection.
    max_vx_forward: float = 0.30   # m/s
    max_vx_backward: float = 0.15  # m/s (walking backwards is riskier)
    max_vy: float = 0.20           # m/s
    max_yaw: float = 0.40          # rad/s

    # Acceleration limits (smooth start, faster slow-down).
    accel_linear: float = 0.5      # m/s^2
    decel_linear: float = 1.0      # m/s^2
    accel_yaw: float = 1.0         # rad/s^2
    decel_yaw: float = 2.0         # rad/s^2

    deadband: float = 0.08         # normalized stick units

    # Dead-man: if no joystick message arrives for this long, stop.
    command_timeout: float = 0.30  # s
    # Each SetVelocity only lasts this long on the robot, so the robot
    # stops by itself even if this whole process freezes.
    velocity_duration: float = 0.40  # s

    loop_hz: float = 20.0
    fsm_check_period: float = 1.0  # s
    allowed_fsm_ids: tuple[int, ...] = (500,)

    lease_idle_timeout: float = 30.0  # s without any message -> auto lock
    max_pin_failures: int = 5
    pin_lockout_seconds: float = 60.0

    mode_change_cooldown: float = 2.0  # s between mode requests
    gesture_hold_seconds: float = 2.0  # hold sustained gestures, then release
    gesture_allowed_fsm_ids: tuple[int, ...] = (500,)
    visitor_gesture_cooldown: float = 4.0  # s after a gesture ends
    handshake_hold_seconds: float = 3.0  # time for the person to shake
    robot_show_enabled: bool = True  # visitor Robot Show works without PIN


class TeleopError(Exception):
    """Base class for errors reported to the operator."""


class PinRejected(TeleopError):
    pass


class PinLockedOut(TeleopError):
    pass


class LeaseBusy(TeleopError):
    pass


class InvalidToken(TeleopError):
    pass


class ModeRejected(TeleopError):
    pass


@dataclass
class _Lease:
    token: str
    operator: str
    created_at: float
    last_seen: float


@dataclass
class _Vel:
    vx: float = 0.0
    vy: float = 0.0
    yaw: float = 0.0

    def is_zero(self) -> bool:
        return self.vx == 0.0 and self.vy == 0.0 and self.yaw == 0.0


def _approach(current: float, target: float, accel: float, decel: float,
              dt: float) -> float:
    """Move `current` toward `target` with separate accel/decel limits."""
    slowing = abs(target) < abs(current) or (current * target < 0)
    rate = decel if slowing else accel
    step = rate * dt
    if abs(target - current) <= step:
        return target
    return current + math.copysign(step, target - current)


class TeleopController:
    """
    Single owner of G1 locomotion commands for operator teleoperation.

    Safety layers (software only - the physical E-stop stays primary):
      * PIN-protected lease: one operator at a time, server-side PIN.
      * Dead-man: no fresh joystick message within command_timeout -> stop.
      * Short SetVelocity durations: robot stops on its own if we die.
      * Speed clamps and acceleration limits.
      * Motion only while FSM is in allowed_fsm_ids (default 500).
      * Latched software E-stop; must be reset explicitly by the operator.
      * Any backend/RPC error latches the E-stop.

    All robot I/O happens in step() (the control loop thread), except
    stop()/estop(), which send StopMove immediately.
    """

    def __init__(
        self,
        backend: MotionBackend,
        pin: str | None,
        limits: TeleopLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backend = backend
        self.limits = limits or TeleopLimits()
        self.clock = clock
        self._pin = pin or ""

        self._state_lock = threading.Lock()
        self._io_lock = threading.Lock()

        self._lease: _Lease | None = None
        self._pin_failures = 0
        self._lockout_until = 0.0

        self._target = _Vel()          # scaled, clamped request
        self._last_cmd_time: float | None = None
        self._output = _Vel()          # what was last sent to the robot
        self._moving = False
        self._last_step: float | None = None

        self._estop = False
        self._estop_reason = ""
        self._fsm_id: int | None = None
        self._fsm_mode: int | None = None
        self._last_mode_change: float | None = None
        self._gesture: str | None = None
        self._gesture_result = ""
        self._gesture_ended: float | None = None
        self._demo_enabled = self.limits.robot_show_enabled
        # Counts STOP / E-STOP presses so autonomous clients (guide) can
        # notice an operator stop and cancel themselves.
        self._stop_count = 0
        # How gesture work is run (thread in production, inline in tests).
        self._spawn: Callable[[Callable[[], None]], None] = (
            lambda fn: threading.Thread(
                target=fn, name="teleop-gesture", daemon=True
            ).start()
        )
        self._last_fsm_check: float | None = None
        self._last_error = ""
        self._reason = "locked"

        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    # ------------------------------------------------------------------
    # Lease / authentication
    # ------------------------------------------------------------------

    def unlock(self, pin: str, operator: str = "operator") -> str:
        now = self.clock()
        with self._state_lock:
            self._expire_lease(now)

            if not self._pin:
                raise PinRejected(
                    "Teleop PIN is not configured on the robot server "
                    "(set G1_TELEOP_PIN)."
                )
            if now < self._lockout_until:
                wait = int(self._lockout_until - now) + 1
                raise PinLockedOut(f"Too many wrong PINs. Wait {wait}s.")

            if not hmac.compare_digest(
                str(pin).encode(), self._pin.encode()
            ):
                self._pin_failures += 1
                if self._pin_failures >= self.limits.max_pin_failures:
                    self._pin_failures = 0
                    self._lockout_until = (
                        now + self.limits.pin_lockout_seconds
                    )
                raise PinRejected("Wrong PIN.")

            self._pin_failures = 0

            if self._lease is not None:
                raise LeaseBusy(
                    f"Robot is already controlled by "
                    f"'{self._lease.operator}'."
                )

            token = secrets.token_urlsafe(24)
            self._lease = _Lease(
                token=token,
                operator=(operator or "operator")[:40],
                created_at=now,
                last_seen=now,
            )
            self._clear_command()
            return token

    def lock(self, token: str) -> None:
        with self._state_lock:
            self._check_token(token)
            self._lease = None
            self._clear_command()
        self._send_stop()

    def touch(self, token: str) -> None:
        with self._state_lock:
            self._check_token(token)
            self._lease.last_seen = self.clock()  # type: ignore[union-attr]

    def is_token_valid(self, token: str) -> bool:
        with self._state_lock:
            self._expire_lease(self.clock())
            return self._token_ok(token)

    @property
    def teleop_active(self) -> bool:
        """True while an operator holds the lease (autonomy must yield)."""
        with self._state_lock:
            return self._lease is not None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def command(
        self,
        token: str,
        x: float,
        y: float,
        yaw: float,
        speed_scale: float = 1.0,
    ) -> None:
        """
        Normalized joystick command, each axis in [-1, 1].
        x: forward+, y: left+, yaw: counter-clockwise (left) +.
        """
        values = (x, y, yaw, speed_scale)
        if not all(
            isinstance(v, (int, float)) and math.isfinite(v)
            for v in values
        ):
            self.stop()
            raise ValueError("Joystick command contains invalid values")

        lim = self.limits
        scale = max(0.1, min(1.0, float(speed_scale)))

        def norm(v: float) -> float:
            v = max(-1.0, min(1.0, float(v)))
            return 0.0 if abs(v) < lim.deadband else v

        x, y, yaw = norm(x), norm(y), norm(yaw)

        vx = x * (lim.max_vx_forward if x > 0 else lim.max_vx_backward)
        target = _Vel(
            vx=vx * scale,
            vy=y * lim.max_vy * scale,
            yaw=yaw * lim.max_yaw * scale,
        )

        now = self.clock()
        with self._state_lock:
            self._check_token(token)
            self._lease.last_seen = now  # type: ignore[union-attr]
            self._target = target
            self._last_cmd_time = now

    def stop(self) -> None:
        """Normal stop. Anyone may call it; no token needed."""
        with self._state_lock:
            self._stop_count += 1
            self._clear_command()
        self._send_stop()

    def estop(self, reason: str = "operator") -> None:
        """Latched software E-stop. Anyone may trigger it."""
        with self._state_lock:
            self._estop = True
            self._estop_reason = reason
            self._stop_count += 1
            self._clear_command()
        self._send_stop()

    def reset_estop(self, token: str) -> None:
        with self._state_lock:
            self._check_token(token)
            self._estop = False
            self._estop_reason = ""
            self._last_error = ""
            self._clear_command()

    # ------------------------------------------------------------------
    # Robot mode (FSM) changes
    # ------------------------------------------------------------------

    def request_mode(self, token: str, mode: str) -> int | None:
        """
        Change robot mode: "damp" (FSM 1), "stand_up" (FSM 4) or
        "walk" (FSM 500). Rules:
          * damp is always allowed (also during E-stop or unknown FSM)
          * stand_up only from Damp, walk only from StandUp
          * any motion is stopped first
        Returns the FSM read back after the request.
        """
        if mode not in MODE_TARGETS:
            raise ModeRejected(f"Unknown mode '{mode}'.")
        target = MODE_TARGETS[mode]
        now = self.clock()

        with self._state_lock:
            self._check_token(token)
            self._lease.last_seen = now  # type: ignore[union-attr]
            if (
                self._last_mode_change is not None
                and now - self._last_mode_change
                < self.limits.mode_change_cooldown
            ):
                raise ModeRejected("Please wait a moment between mode changes.")
            if mode != "damp" and self._estop:
                raise ModeRejected("Reset the E-stop first.")
            if mode != "damp" and self._gesture is not None:
                raise ModeRejected("Wait until the gesture has finished.")
            self._clear_command()

        with self._io_lock:
            current = self.backend.get_fsm_id()
            if mode != "damp":
                if current is None:
                    raise ModeRejected("Cannot read the robot FSM.")
                if current != target and current not in MODE_ALLOWED_FROM[mode]:
                    need = " or ".join(
                        str(f) for f in sorted(MODE_ALLOWED_FROM[mode])
                    )
                    raise ModeRejected(
                        f"'{mode}' needs FSM {need} first (robot is at "
                        f"FSM {current})."
                    )

            if self._moving:
                self.backend.stop()
                self._moving = False

            if current != target:
                try:
                    if mode == "damp":
                        self.backend.damp()
                    else:
                        self.backend.set_fsm(target)
                except Exception as exc:
                    raise ModeRejected(f"Robot rejected the request: {exc}")

            fsm = self.backend.get_fsm_id()
            fsm_mode = self.backend.get_fsm_mode() if fsm is not None else None
            with self._state_lock:
                self._last_mode_change = now
                self._fsm_id = fsm
                self._fsm_mode = fsm_mode
                self._last_fsm_check = self.clock()
            return fsm

    # ------------------------------------------------------------------
    # Entertainment: arm gestures
    # ------------------------------------------------------------------

    def perform_gesture(self, token: str, gesture: str) -> None:
        """
        Start an arm gesture. Returns immediately; progress and result
        are reported in status()["gesture"] / ["gesture_result"].

        Rules: lease required, no E-stop, robot in walking mode (FSM 500),
        one gesture at a time. Walking is stopped and the joystick is
        ignored while the gesture runs.
        """
        if gesture not in GESTURES:
            raise ModeRejected(f"Unknown gesture '{gesture}'.")

        with self._state_lock:
            self._check_token(token)
            self._lease.last_seen = self.clock()  # type: ignore[union-attr]
            action_id, label = self._claim_gesture_locked(gesture)

        self._spawn(lambda: self._run_gesture(action_id, label))

    # --- visitor demo mode -------------------------------------------

    def set_demo_mode(self, token: str, enabled: bool) -> None:
        """Operator switches the visitor 'Robot Show' buttons on/off."""
        with self._state_lock:
            self._check_token(token)
            self._demo_enabled = bool(enabled)

    def visitor_gesture(self, gesture: str, by_voice: bool = False) -> None:
        """
        Gesture requested from the visitor screen (no PIN). Only allowed
        when the operator enabled demo mode, for the safe subset, while
        the robot is standing still, with a cooldown between gestures.
        """
        allowed = VOICE_GESTURES if by_voice else VISITOR_GESTURES
        if gesture not in allowed:
            raise ModeRejected("This gesture is not available for visitors.")
        now = self.clock()
        with self._state_lock:
            if not self._demo_enabled:
                raise ModeRejected("The robot show is not active right now.")
            if (
                self._gesture_ended is not None
                and now - self._gesture_ended
                < self.limits.visitor_gesture_cooldown
            ):
                raise ModeRejected("One moment, the robot is resting.")
            if not (self._output.is_zero() and self._target.is_zero()):
                raise ModeRejected("The robot is moving right now.")
            action_id, label = self._claim_gesture_locked(gesture)

        self._spawn(lambda: self._run_gesture(action_id, label))

    def demo_status(self) -> dict:
        """Public status for the visitor screen (no secrets)."""
        now = self.clock()
        with self._state_lock:
            reason = ""
            if not self._demo_enabled:
                reason = "off"
            elif self._estop:
                reason = "stopped"
            elif self._fsm_id not in self.limits.gesture_allowed_fsm_ids:
                reason = "not_ready"
            elif self._gesture is not None:
                reason = "busy"
            elif not (self._output.is_zero() and self._target.is_zero()):
                reason = "moving"
            elif (
                self._gesture_ended is not None
                and now - self._gesture_ended
                < self.limits.visitor_gesture_cooldown
            ):
                reason = "resting"
            return {
                "demo_enabled": self._demo_enabled,
                "available": reason == "",
                "reason": reason,
                "gesture": self._gesture,
                "gestures": [
                    {"key": key, "label": GESTURES[key][1]}
                    for key in VISITOR_GESTURES
                ],
            }

    def _claim_gesture_locked(self, gesture: str) -> tuple[int, str]:
        # Call with _state_lock held. Shared checks for all gestures.
        action_id, label = GESTURES[gesture]
        if self._estop:
            raise ModeRejected("Reset the E-stop first.")
        if self._gesture is not None:
            raise ModeRejected("A gesture is already running.")
        if self._fsm_id not in self.limits.gesture_allowed_fsm_ids:
            raise ModeRejected(
                "Gestures need walking mode (FSM 500), standing still."
            )
        self._gesture = gesture
        self._gesture_result = f"{label}..."
        self._clear_command()
        return action_id, label

    def _run_gesture(self, action_id: int, label: str) -> None:
        result = f"{label}: done"
        try:
            self._send_stop()  # make sure the legs are standing still
            code = self.backend.execute_arm_action(action_id)
            if code == 7401:
                self.backend.execute_arm_action(ARM_RELEASE)
                result = f"{label}: {ARM_ERRORS[7401]}"
            elif code != 0:
                result = f"{label}: " + ARM_ERRORS.get(
                    code, f"robot returned error {code}."
                )
            elif action_id in SUSTAINED_GESTURES:
                time.sleep(
                    self.limits.handshake_hold_seconds
                    if action_id == HANDSHAKE_ID
                    else self.limits.gesture_hold_seconds
                )
                self.backend.execute_arm_action(ARM_RELEASE)
        except Exception as exc:
            result = f"{label}: failed ({exc})"
        finally:
            with self._state_lock:
                self._gesture = None
                self._gesture_result = result
                self._gesture_ended = self.clock()
                self._clear_command()

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------

    def step(self) -> None:
        """One control tick. Call at limits.loop_hz from a single thread."""
        with self._io_lock:
            now = self.clock()
            self._maybe_refresh_fsm(now)

            with self._state_lock:
                dt = (
                    0.0 if self._last_step is None
                    else max(0.0, min(0.2, now - self._last_step))
                )
                self._last_step = now
                self._expire_lease(now)

                reason = self._blocking_reason(now)
                self._reason = reason or "driving"

                if reason is not None:
                    # Hard stop: no ramp-down when a safety check fails.
                    self._output = _Vel()
                    if reason != "idle":
                        self._target = _Vel()
                else:
                    lim = self.limits
                    o, t = self._output, self._target
                    self._output = _Vel(
                        vx=_approach(o.vx, t.vx, lim.accel_linear,
                                     lim.decel_linear, dt),
                        vy=_approach(o.vy, t.vy, lim.accel_linear,
                                     lim.decel_linear, dt),
                        yaw=_approach(o.yaw, t.yaw, lim.accel_yaw,
                                      lim.decel_yaw, dt),
                    )
                out = self._output
                was_moving = self._moving
                if reason is None and out.is_zero() and self._target.is_zero():
                    self._reason = "ready"

            try:
                if not out.is_zero():
                    self.backend.set_velocity(
                        out.vx, out.vy, out.yaw,
                        self.limits.velocity_duration,
                    )
                    self._moving = True
                elif was_moving:
                    self.backend.stop()
                    self._moving = False
            except Exception as exc:  # latch on any RPC failure
                with self._state_lock:
                    self._estop = True
                    self._estop_reason = "backend_error"
                    self._last_error = str(exc)
                    self._clear_command()
                    self._output = _Vel()
                try:
                    self.backend.stop()
                finally:
                    self._moving = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._run, name="teleop-loop", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.stop()

    def _run(self) -> None:
        period = 1.0 / self.limits.loop_hz
        while self._running.is_set():
            started = time.monotonic()
            try:
                self.step()
            except Exception as exc:  # never let the loop die silently
                self._last_error = f"loop error: {exc}"
            time.sleep(max(0.0, period - (time.monotonic() - started)))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self, token: str | None = None) -> dict:
        now = self.clock()
        with self._state_lock:
            self._expire_lease(now)
            lease = self._lease
            age = (
                None if self._last_cmd_time is None
                else round(now - self._last_cmd_time, 3)
            )
            return {
                "state": self._reason,
                "teleop_active": lease is not None,
                "you_have_control": (
                    token is not None and self._token_ok(token)
                ),
                "operator": lease.operator if lease else None,
                "estop": self._estop,
                "estop_reason": self._estop_reason,
                "fsm_id": self._fsm_id,
                "fsm_mode": self._fsm_mode,
                "gesture": self._gesture,
                "gesture_result": self._gesture_result,
                "demo_enabled": self._demo_enabled,
                "stop_count": self._stop_count,
                "locomotion_ready": (
                    self._fsm_id in self.limits.allowed_fsm_ids
                ),
                "output": {
                    "vx": round(self._output.vx, 3),
                    "vy": round(self._output.vy, 3),
                    "yaw": round(self._output.yaw, 3),
                },
                "last_command_age": age,
                "last_error": self._last_error,
                "limits": asdict(self.limits),
            }

    # ------------------------------------------------------------------
    # Internals (call with _state_lock held unless noted)
    # ------------------------------------------------------------------

    def _blocking_reason(self, now: float) -> str | None:
        if self._estop:
            return "estop"
        if self._lease is None:
            return "locked"
        if self._gesture is not None:
            return "gesture"
        if self._fsm_id not in self.limits.allowed_fsm_ids:
            return "not_locomotion_ready"
        if (
            self._last_cmd_time is None
            or now - self._last_cmd_time > self.limits.command_timeout
        ):
            return "idle"
        return None

    def _maybe_refresh_fsm(self, now: float) -> None:
        # Called with _io_lock held (performs RPC).
        if (
            self._last_fsm_check is not None
            and now - self._last_fsm_check < self.limits.fsm_check_period
        ):
            return
        self._last_fsm_check = now
        fsm = self.backend.get_fsm_id()
        mode = self.backend.get_fsm_mode() if fsm is not None else None
        with self._state_lock:
            self._fsm_id = fsm
            self._fsm_mode = mode

    def _expire_lease(self, now: float) -> None:
        if (
            self._lease is not None
            and now - self._lease.last_seen > self.limits.lease_idle_timeout
        ):
            self._lease = None
            self._clear_command()

    def _clear_command(self) -> None:
        self._target = _Vel()
        self._output = _Vel()
        self._last_cmd_time = None

    def _token_ok(self, token: str | None) -> bool:
        return (
            self._lease is not None
            and token is not None
            and hmac.compare_digest(
                str(token).encode(), self._lease.token.encode()
            )
        )

    def _check_token(self, token: str | None) -> None:
        self._expire_lease(self.clock())
        if not self._token_ok(token):
            raise InvalidToken("Not authorized or session expired.")

    def _send_stop(self) -> None:
        # Waits for an in-flight SetVelocity, then stops - so a stale
        # velocity can never be sent after this stop.
        with self._io_lock:
            try:
                self.backend.stop()
            finally:
                self._moving = False
