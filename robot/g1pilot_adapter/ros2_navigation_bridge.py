from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from robot.g1pilot_adapter.navigation_bridge import VelocityCommand


@dataclass(frozen=True)
class JoyMapping:
    max_forward_speed: float = 0.5
    max_lateral_speed: float = 0.5
    max_yaw_speed: float = 0.5
    command_duration: float = 0.2
    deadband: float = 0.03


class G1PilotJoyConverter:
    """
    Convert G1Pilot Joy messages into velocity commands.

    Pure conversion only:
    - No ROS subscription
    - No robot connection
    - No motor commands
    - No automatic authorization
    """

    def __init__(self, mapping: JoyMapping | None = None):
        self.mapping = mapping or JoyMapping()

    def convert(
        self,
        axes: Sequence[float],
        buttons: Sequence[int],
        *,
        enabled: bool = False,
    ) -> VelocityCommand:
        zero = VelocityCommand(
            vx=0.0,
            vy=0.0,
            yaw=0.0,
            duration=self.mapping.command_duration,
        )

        if not enabled:
            return zero

        if len(axes) < 8 or len(buttons) < 14:
            raise ValueError("Invalid G1Pilot Joy message dimensions")

        if not all(math.isfinite(float(v)) for v in axes):
            raise ValueError("Joy axes contain non-finite values")

        if not all(-1.0 <= float(v) <= 1.0 for v in axes):
            raise ValueError("Joy axes exceed normalized range")

        if any(value not in (0, 1) for value in buttons):
            raise ValueError("Invalid joystick button value")

        if buttons[8] != 1:
            return zero

        vx = -float(axes[1]) * self.mapping.max_forward_speed
        vy = -float(axes[0]) * self.mapping.max_lateral_speed
        yaw = -float(axes[2]) * self.mapping.max_yaw_speed

        def deadband(value: float) -> float:
            return 0.0 if abs(value) < self.mapping.deadband else value

        return VelocityCommand(
            vx=deadband(vx),
            vy=deadband(vy),
            yaw=deadband(yaw),
            duration=self.mapping.command_duration,
        )