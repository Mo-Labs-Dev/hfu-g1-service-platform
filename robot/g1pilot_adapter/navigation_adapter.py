from __future__ import annotations

import math

from modules.navigation.models import NavigationGoal
from robot.g1pilot_adapter.navigation_bridge import (
    MockMotionAdapter,
    NavigationBridge,
    VelocityCommand,
)


class G1PilotNavigationAdapter:
    """
    Navigation adapter for the HFU G1 Service Platform.

    MOCK:
        Simulates navigation goals and velocity commands.

    REAL:
        Reserved for G1Pilot ROS 2 integration.
        Physical navigation remains locked.
    """

    def __init__(self, mode: str = "mock") -> None:
        if mode not in ("mock", "real"):
            raise ValueError("mode must be 'mock' or 'real'")

        self.mode = mode
        self.connected = False
        self.active_goal: NavigationGoal | None = None

        self.mock_motion = MockMotionAdapter()
        self.bridge = NavigationBridge(self.mock_motion)

    def connect(self) -> None:
        if self.connected:
            return

        if self.mode == "real":
            print("[G1PilotAdapter] REAL navigation remains locked.")
        else:
            print("[G1PilotAdapter] Connected in MOCK mode.")

        self.connected = True

    def send_goal(self, goal: NavigationGoal) -> None:
        if not self.connected:
            raise RuntimeError("Navigation adapter not connected.")

        if self.mode != "mock":
            raise RuntimeError("Real navigation is locked.")

        if self.active_goal is not None:
            raise RuntimeError("Navigation goal already active.")

        if not isinstance(goal.name, str) or not goal.name.strip():
            raise ValueError("Goal name cannot be empty.")

        if not all(
            math.isfinite(value)
            for value in (goal.x, goal.y, goal.yaw)
        ):
            raise ValueError("Goal coordinates must be finite.")

        self.active_goal = goal
        self.bridge.enable()

        print(
            f"[NAV MOCK] Goal accepted: {goal.name} "
            f"x={goal.x}, y={goal.y}, yaw={goal.yaw}"
        )

    def send_mock_velocity(
        self,
        command: VelocityCommand,
        created_at: float,
    ) -> VelocityCommand:
        """
        Forward a simulated controller velocity.

        This does not convert destination coordinates to velocity.
        """
        if self.mode != "mock":
            raise RuntimeError("Mock velocity unavailable in real mode.")

        if self.active_goal is None:
            raise RuntimeError("No active navigation goal.")

        return self.bridge.send_velocity(command, created_at)

    def complete_goal(self) -> None:
        """Simulate a confirmed goal arrival."""
        if self.mode != "mock":
            raise RuntimeError("Real goal completion is not implemented.")

        if self.active_goal is None:
            raise RuntimeError("No active navigation goal.")

        self.bridge.disable()
        print(f"[NAV MOCK] Arrived: {self.active_goal.name}")
        self.active_goal = None

    def stop(self) -> None:
        if self.mode == "mock":
            self.bridge.disable()
            self.active_goal = None
            print("[G1PilotAdapter] MOCK navigation stopped.")
            return

        raise RuntimeError(
            "Real navigation stop is not implemented. "
            "Physical navigation must remain disabled."
        )