from modules.navigation.models import NavigationGoal


class G1PilotNavigationAdapter:
    """
    Adapter between the thesis NavigationModule and G1Pilot.

    Modes:
        mock:
            Development without a physical robot.

        real:
            Reserved for communication with the real G1Pilot ROS 2 system.

    Physical robot motion is intentionally disabled until the
    G1Pilot locomotion startup procedure has been validated.
    """

    def __init__(self, mode: str = "mock"):
        if mode not in ("mock", "real"):
            raise ValueError("mode must be 'mock' or 'real'")

        self.mode = mode
        self.connected = False

    def connect(self) -> None:
        """Initialize the adapter."""

        if self.mode == "mock":
            print("[G1PilotAdapter] Connected in MOCK mode.")
            self.connected = True
            return

        # Real ROS 2 / G1Pilot connection will be implemented here.
        print("[G1PilotAdapter] REAL mode selected.")
        print("[G1PilotAdapter] Physical motion is currently locked.")
        self.connected = True

    def send_goal(self, goal: NavigationGoal) -> None:
        """Send a navigation goal."""

        if not self.connected:
            raise RuntimeError("G1Pilot adapter is not connected.")

        if self.mode == "mock":
            print(
                f"[G1PilotAdapter] MOCK navigation: "
                f"{goal.name} -> "
                f"x={goal.x}, y={goal.y}, yaw={goal.yaw}"
            )
            return

        raise RuntimeError(
            "Real navigation is locked until G1 locomotion "
            "startup and safety checks are validated."
        )

    def stop(self) -> None:
        """Request navigation stop."""

        if not self.connected:
            return

        if self.mode == "mock":
            print("[G1PilotAdapter] MOCK stop requested.")
            return

        # Real StopMove / G1Pilot stop integration will go here.
        print("[G1PilotAdapter] REAL stop requested.")
