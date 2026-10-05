from modules.navigation.models import NavigationGoal, NavigationStatus
from robot.g1pilot_adapter.navigation_adapter import G1PilotNavigationAdapter


class NavigationModule:
    """
    High-level navigation module for the HFU G1 Service Platform.
    """

    def __init__(self, adapter: G1PilotNavigationAdapter):
        self.adapter = adapter
        self.status = NavigationStatus.IDLE
        self.current_goal = None

    def initialize(self) -> None:
        """Initialize the navigation system."""
        self.adapter.connect()
        self.status = NavigationStatus.IDLE

    def go_to(self, goal: NavigationGoal) -> None:
        """Start navigation toward a destination."""

        if self.status == NavigationStatus.NAVIGATING:
            raise RuntimeError("Robot is already navigating.")

        self.current_goal = goal
        self.status = NavigationStatus.NAVIGATING

        try:
            self.adapter.send_goal(goal)
        except Exception:
            self.status = NavigationStatus.FAILED
            self.current_goal = None
            raise

    def stop(self) -> None:
        """Stop the current navigation task."""

        self.adapter.stop()
        self.status = NavigationStatus.STOPPED
        self.current_goal = None

    def get_status(self) -> NavigationStatus:
        """Return the current navigation status."""
        return self.status
