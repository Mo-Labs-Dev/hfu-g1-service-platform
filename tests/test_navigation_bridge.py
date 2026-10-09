import unittest

from robot.g1pilot_adapter.navigation_bridge import (
    MockMotionAdapter,
    NavigationBridge,
    NavigationLimits,
    VelocityCommand,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class NavigationBridgeTests(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.motion = MockMotionAdapter()
        self.bridge = NavigationBridge(
            motion=self.motion,
            clock=self.clock,
        )

    def test_disabled_by_default(self):
        with self.assertRaises(RuntimeError):
            self.bridge.send_velocity(
                VelocityCommand(vx=0.1),
                created_at=self.clock(),
            )

        self.assertEqual(len(self.motion.commands), 0)

    def test_valid_command(self):
        self.bridge.enable()

        result = self.bridge.send_velocity(
            VelocityCommand(vx=0.1, duration=0.2),
            created_at=self.clock(),
        )

        self.assertEqual(result.vx, 0.1)
        self.assertEqual(len(self.motion.commands), 1)

    def test_velocity_limits(self):
        self.bridge.enable()

        result = self.bridge.send_velocity(
            VelocityCommand(
                vx=2.0,
                vy=-2.0,
                yaw=3.0,
                duration=5.0,
            ),
            created_at=self.clock(),
        )

        self.assertEqual(result.vx, 0.20)
        self.assertEqual(result.vy, -0.10)
        self.assertEqual(result.yaw, 0.20)
        self.assertEqual(result.duration, 0.5)

    def test_expired_command(self):
        self.bridge.enable()
        self.clock.advance(1.0)

        with self.assertRaises(TimeoutError):
            self.bridge.send_velocity(
                VelocityCommand(vx=0.1),
                created_at=100.0,
            )

        self.assertFalse(self.bridge.enabled)
        self.assertEqual(self.motion.stop_count, 1)

    def test_explicit_stop(self):
        self.bridge.enable()
        self.bridge.stop()

        self.assertFalse(self.bridge.enabled)
        self.assertEqual(self.motion.stop_count, 1)

    def test_watchdog_timeout(self):
        self.bridge.enable()

        self.bridge.send_velocity(
            VelocityCommand(vx=0.1),
            created_at=self.clock(),
        )

        self.clock.advance(1.0)

        self.assertTrue(self.bridge.check_timeout())
        self.assertFalse(self.bridge.enabled)

    def test_invalid_command(self):
        self.bridge.enable()

        with self.assertRaises(ValueError):
            self.bridge.send_velocity(
                VelocityCommand(vx=float("nan")),
                created_at=self.clock(),
            )

        self.assertFalse(self.bridge.enabled)


if __name__ == "__main__":
    unittest.main()