import unittest

from modules.navigation.models import (
    NavigationGoal,
    NavigationStatus,
)
from modules.navigation.navigation_module import NavigationModule
from robot.g1pilot_adapter.navigation_adapter import (
    G1PilotNavigationAdapter,
)
from robot.g1pilot_adapter.navigation_bridge import VelocityCommand


class NavigationIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.adapter = G1PilotNavigationAdapter(mode="mock")
        self.navigation = NavigationModule(self.adapter)
        self.navigation.initialize()

    def test_initial_state(self):
        self.assertEqual(
            self.navigation.get_status(),
            NavigationStatus.IDLE,
        )

    def test_goal_accepted(self):
        goal = NavigationGoal("3D Printer", 1.0, 2.0)

        self.navigation.go_to(goal)

        self.assertEqual(
            self.navigation.get_status(),
            NavigationStatus.NAVIGATING,
        )
        self.assertTrue(self.adapter.bridge.enabled)

    def test_mock_velocity(self):
        self.navigation.go_to(
            NavigationGoal("Lab Entrance", 1.0, 0.0)
        )

        now = self.adapter.bridge.clock()

        result = self.adapter.send_mock_velocity(
            VelocityCommand(vx=0.15, duration=0.2),
            created_at=now,
        )

        self.assertEqual(result.vx, 0.15)
        self.assertEqual(len(self.adapter.mock_motion.commands), 1)

    def test_arrival(self):
        self.navigation.go_to(
            NavigationGoal("3D Printer", 1.0, 2.0)
        )

        self.navigation.mark_arrived()

        self.assertEqual(
            self.navigation.get_status(),
            NavigationStatus.ARRIVED,
        )
        self.assertFalse(self.adapter.bridge.enabled)
        self.assertIsNone(self.adapter.active_goal)

    def test_stop(self):
        self.navigation.go_to(
            NavigationGoal("Lab Entrance", 1.0, 0.0)
        )

        self.navigation.stop()

        self.assertEqual(
            self.navigation.get_status(),
            NavigationStatus.STOPPED,
        )
        self.assertFalse(self.adapter.bridge.enabled)

    def test_real_navigation_locked(self):
        adapter = G1PilotNavigationAdapter(mode="real")
        navigation = NavigationModule(adapter)
        navigation.initialize()

        with self.assertRaises(RuntimeError):
            navigation.go_to(
                NavigationGoal("3D Printer", 1.0, 2.0)
            )

        self.assertEqual(
            navigation.get_status(),
            NavigationStatus.IDLE,
        )

    def test_invalid_goal(self):
        with self.assertRaises(ValueError):
            self.navigation.go_to(
                NavigationGoal("Invalid", float("nan"), 0.0)
            )

        self.assertEqual(
            self.navigation.get_status(),
            NavigationStatus.IDLE,
        )


if __name__ == "__main__":
    unittest.main()