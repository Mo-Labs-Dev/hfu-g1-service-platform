from __future__ import annotations

import math
import time
from typing import Callable, Sequence

from robot.g1pilot_adapter.navigation_bridge import (
    MockMotionAdapter,
    NavigationBridge,
    NavigationLimits,
    VelocityCommand,
)
from robot.g1pilot_adapter.ros2_navigation_bridge import (
    G1PilotJoyConverter,
)


class NavigationSupervisor:
    """
    Mock-only navigation command supervisor.

    Explicit authorization is required.
    Commands are validated and checked for freshness.
    An external periodic caller must invoke tick().

    This is not a hardware emergency stop or a complete
    real-time watchdog.
    """

    def __init__(
        self,
        motion: MockMotionAdapter,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 0.5,
    ) -> None:
        if type(motion) is not MockMotionAdapter:
            raise TypeError(
                "NavigationSupervisor currently supports "
                "MockMotionAdapter only"
            )

        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be positive and finite")

        self.clock = clock
        self.timeout = timeout

        self.converter = G1PilotJoyConverter()

        self.bridge = NavigationBridge(
            motion=motion,
            limits=NavigationLimits(
                command_timeout=timeout,
            ),
            clock=clock,
        )

        self.authorized = False
        self.last_received: float | None = None
        self.enabled_at: float | None = None

    def enable(self) -> None:
        if self.authorized:
            return

        now = self.clock()

        self.authorized = True
        self.enabled_at = now
        self.last_received = None

        self.bridge.enable()

    def disable(self) -> None:
        self.authorized = False
        self.enabled_at = None
        self.last_received = None

        self.bridge.disable()

    def receive_joy(
        self,
        axes: Sequence[float],
        buttons: Sequence[int],
        created_at: float,
    ) -> VelocityCommand:
        if not self.authorized:
            raise RuntimeError("Navigation is not authorized")

        now = self.clock()

        if (
            not math.isfinite(created_at)
            or created_at > now
            or now - created_at > self.timeout
        ):
            self.disable()
            raise TimeoutError("Joystick command is stale")

        if self._expired(now):
            self.disable()
            raise TimeoutError("Command stream timed out")

        try:
            command = self.converter.convert(
                axes,
                buttons,
                enabled=True,
            )

            result = self.bridge.send_velocity(
                command,
                created_at=created_at,
            )

        except Exception:
            self.disable()
            raise

        self.last_received = now
        return result

    def _expired(self, now: float) -> bool:
        reference = (
            self.last_received
            if self.last_received is not None
            else self.enabled_at
        )

        if reference is None:
            return False

        return now - reference > self.timeout

    def tick(self) -> bool:
        """
        Must be called periodically by an external scheduler.

        Returns True if a timeout caused navigation to stop.
        """
        if not self.authorized:
            return False

        if self._expired(self.clock()):
            self.disable()
            return True

        return False