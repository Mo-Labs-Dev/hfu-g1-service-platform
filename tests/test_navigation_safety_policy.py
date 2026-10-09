import unittest

from robot.g1pilot_adapter.navigation_safety_policy import (
    NavigationSafetyPolicy,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class NavigationSafetyPolicyTests(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.policy = NavigationSafetyPolicy(clock=self.clock)

    def prepare(self):
        self.policy.update_odometry(0.0, 0.0, 0.0)
        self.policy.update_path(
            [(0.0, 0.0), (1.0, 0.0)],
            "map",
            "map",
        )

    def test_disabled_by_default(self):
        self.prepare()
        self.assertFalse(self.policy.can_move())

    def test_valid_navigation(self):
        self.prepare()
        self.policy.enable()
        self.assertTrue(self.policy.can_move())

    def test_missing_odometry(self):
        self.policy.update_path([(1.0, 0.0)], "map", "map")
        self.policy.enable()
        self.assertFalse(self.policy.can_move())

    def test_stale_odometry(self):
        self.prepare()
        self.policy.enable()
        self.clock.advance(0.6)
        self.assertFalse(self.policy.can_move())

    def test_invalid_odometry(self):
        self.prepare()
        self.policy.update_odometry(float("nan"), 0.0, 0.0)
        self.policy.enable()
        self.assertFalse(self.policy.can_move())

    def test_empty_path(self):
        self.policy.update_odometry(0.0, 0.0, 0.0)
        self.policy.update_path([], "map", "map")
        self.policy.enable()
        self.assertFalse(self.policy.can_move())

    def test_frame_mismatch(self):
        self.policy.update_odometry(0.0, 0.0, 0.0)
        self.policy.update_path([(1.0, 0.0)], "map", "odom")
        self.policy.enable()
        self.assertFalse(self.policy.can_move())

    def test_expired_path(self):
        self.prepare()
        self.policy.enable()
        self.clock.advance(2.1)
        self.assertFalse(self.policy.can_move())

    def test_disable(self):
        self.prepare()
        self.policy.enable()
        self.policy.disable()
        self.assertFalse(self.policy.can_move())


if __name__ == "__main__":
    unittest.main()