from modules.navigation.models import NavigationGoal


class G1PilotNavigationAdapter:
    """
    Adapter between the thesis navigation module and G1Pilot.

    The NavigationModule should not communicate directly with
    ROS 2 or the Unitree SDK.
    """

    def __init__(self):
        self.connected = False

    def connect(self) -> None:
        """
        Prepare the connection to G1Pilot.
        """
        self.connected = True

    def send_goal(self, goal: NavigationGoal) -> None:
        """
        Send a navigation goal to G1Pilot.
        """

        if not self.connected:
            raise RuntimeError("G1Pilot adapter is not connected.")

        print(
            f"[G1PilotAdapter] Navigation goal: "
            f"{goal.name} -> x={goal.x}, y={goal.y}, yaw={goal.yaw}"
        )

    def stop(self) -> None:
        """
        Request navigation to stop.
        """

        if not self.connected:
            return

        print("[G1PilotAdapter] Stop requested.")
