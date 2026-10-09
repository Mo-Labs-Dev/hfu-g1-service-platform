from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class VelocityCommand:
    vx: float = 0.0
    vy: float = 0.0
    yaw: float = 0.0
    duration: float = 0.2


@dataclass(frozen=True)
class NavigationLimits:
    max_vx: float = 0.20
    max_vy: float = 0.10
    max_yaw: float = 0.20
    max_duration: float = 0.5
    command_timeout: float = 0.5


class MotionAdapter(Protocol):
    def move(
        self,
        vx: float,
        vy: float,
        yaw: float,
        duration: float,
    ) -> None:
        ...

    def stop(self) -> None:
        ...


class MockMotionAdapter:
    """Test navigation commands without connecting to a robot."""

    def __init__(self) -> None:
        self.commands: list[VelocityCommand] = []
        self.stop_count = 0

    def move(
        self,
        vx: float,
        vy: float,
        yaw: float,
        duration: float,
    ) -> None:
        command = VelocityCommand(vx, vy, yaw, duration)
        self.commands.append(command)
        print(f"[MOCK] MOVE {command}")

    def stop(self) -> None:
        self.stop_count += 1
        print("[MOCK] STOP")


class NavigationBridge:
    """
    Safety-gated velocity interface between navigation controllers
    and the G1 locomotion adapter.

    Disabled by default.

    This class provides command-age checks, speed limits, and
    explicit software stopping. It is not a hardware emergency stop.

    Important:
    The existing G1PythonAdapter.move() is a blocking method.
    Therefore, this bridge is initially intended for mock testing.
    Do not connect it to live autonomous navigation until a
    non-blocking controller and independent watchdog exist.
    """

    def __init__(
        self,
        motion: MotionAdapter,
        limits: NavigationLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.motion = motion
        self.limits = limits or NavigationLimits()
        self.clock = clock
        self.enabled = False
        self.last_command_time: float | None = None

    def enable(self) -> None:
        if self.enabled:
            return

        self.enabled = True
        self.last_command_time = None
        print("[NAV] Enabled")

    def disable(self) -> None:
        self.enabled = False
        self.last_command_time = None
        try:
            self.motion.stop()
        finally:
            print("[NAV] Disabled")

    def stop(self) -> None:
        self.disable()

    @staticmethod
    def _clamp(value: float, maximum: float) -> float:
        return max(-maximum, min(maximum, value))

    def send_velocity(
        self,
        command: VelocityCommand,
        created_at: float,
    ) -> VelocityCommand:
        if not self.enabled:
            raise RuntimeError("Navigation is disabled")

        values = (
            command.vx,
            command.vy,
            command.yaw,
            command.duration,
            created_at,
        )

        if not all(math.isfinite(value) for value in values):
            self.disable()
            raise ValueError("Navigation command contains invalid values")

        now = self.clock()
        age = now - created_at

        if age < 0 or age > self.limits.command_timeout:
            self.disable()
            raise TimeoutError(
                f"Navigation command expired: age={age:.3f}s"
            )

        if command.duration <= 0:
            self.disable()
            raise ValueError("Movement duration must be positive")

        safe_command = VelocityCommand(
            vx=self._clamp(command.vx, self.limits.max_vx),
            vy=self._clamp(command.vy, self.limits.max_vy),
            yaw=self._clamp(command.yaw, self.limits.max_yaw),
            duration=min(
                command.duration,
                self.limits.max_duration,
            ),
        )

        try:
            self.motion.move(
                vx=safe_command.vx,
                vy=safe_command.vy,
                yaw=safe_command.yaw,
                duration=safe_command.duration,
            )
        except Exception:
            self.disable()
            raise

        self.last_command_time = now
        return safe_command

    def check_timeout(self) -> bool:
        """
        Check whether commands have stopped arriving.

        Must be called periodically by an independent supervisor
        in future implementations.
        """
        if not self.enabled or self.last_command_time is None:
            return False

        if (
            self.clock() - self.last_command_time
            > self.limits.command_timeout
        ):
            self.disable()
            return True

        return False