from __future__ import annotations

from modules.navigation.models import (
    NavigationGoal,
    NavigationStatus,
)
from robot.g1pilot_adapter.navigation_adapter import (
    G1PilotNavigationAdapter,
)


class NavigationModule:
    """
    High-level navigation task management.

    Manages goal lifecycle independently of robot hardware.
    """

    def __init__(self, adapter: G1PilotNavigationAdapter):
        self.adapter = adapter
        self.status = NavigationStatus.IDLE
        self.current_goal: NavigationGoal | None = None

    def initialize(self) -> None:
        self.adapter.connect()
        self.status = NavigationStatus.IDLE
        self.current_goal = None

    def go_to(self, goal: NavigationGoal) -> None:
        if self.status == NavigationStatus.NAVIGATING:
            raise RuntimeError("Robot is already navigating.")

        self.adapter.send_goal(goal)

        self.current_goal = goal
        self.status = NavigationStatus.NAVIGATING

        print(f"[NavigationModule] Navigating to {goal.name}")

    def mark_arrived(self) -> None:
        """
        Complete an active navigation task.

        In MOCK mode this simulates arrival.
        Future REAL mode requires verified pose and goal tolerance.
        """
        if self.status != NavigationStatus.NAVIGATING:
            raise RuntimeError("No active navigation task.")

        self.adapter.complete_goal()

        self.current_goal = None
        self.status = NavigationStatus.ARRIVED

        print("[NavigationModule] Goal completed.")

    def stop(self) -> None:
        try:
            self.adapter.stop()
        except Exception:
            self.status = NavigationStatus.FAILED
            raise

        self.current_goal = None
        self.status = NavigationStatus.STOPPED

    def get_status(self) -> NavigationStatus:
        return self.status