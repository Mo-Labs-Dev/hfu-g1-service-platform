import unittest

from robot.g1pilot_adapter.navigation_bridge import (
    MockMotionAdapter,
)
from robot.g1pilot_adapter.navigation_supervisor import (
    NavigationSupervisor,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class NavigationSupervisorTests(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.motion = MockMotionAdapter()

        self.supervisor = NavigationSupervisor(
            motion=self.motion,
            clock=self.clock,
            timeout=0.5,
        )

        self.axes = [0.0] * 8
        self.buttons = [0] * 14
        self.axes[1] = -0.2
        self.buttons[8] = 1

    def send(self, created_at=None):
        if created_at is None:
            created_at = self.clock()

        return self.supervisor.receive_joy(
            self.axes,
            self.buttons,
            created_at,
        )

    def test_disabled_by_default(self):
        with self.assertRaises(RuntimeError):
            self.send()

        self.assertEqual(len(self.motion.commands), 0)

    def test_authorized_movement(self):
        self.supervisor.enable()

        result = self.send()

        self.assertAlmostEqual(result.vx, 0.1)
        self.assertEqual(len(self.motion.commands), 1)

    def test_timeout_after_command(self):
        self.supervisor.enable()
        self.send()

        self.clock.advance(0.6)

        self.assertTrue(self.supervisor.tick())
        self.assertFalse(self.supervisor.authorized)
        self.assertGreater(self.motion.stop_count, 0)

    def test_timeout_without_first_command(self):
        self.supervisor.enable()

        self.clock.advance(0.6)

        self.assertTrue(self.supervisor.tick())
        self.assertFalse(self.supervisor.authorized)

    def test_stale_message_rejected(self):
        self.supervisor.enable()

        self.clock.advance(0.6)

        with self.assertRaises(TimeoutError):
            self.send(created_at=100.0)

        self.assertFalse(self.supervisor.authorized)

    def test_invalid_message_disables(self):
        self.supervisor.enable()

        with self.assertRaises(ValueError):
            self.supervisor.receive_joy(
                [float("nan")] * 8,
                self.buttons,
                self.clock(),
            )

        self.assertFalse(self.supervisor.authorized)

    def test_disable_requires_reauthorization(self):
        self.supervisor.enable()
        self.supervisor.disable()

        with self.assertRaises(RuntimeError):
            self.send()

    def test_no_stale_replay(self):
        self.supervisor.enable()
        self.send()

        self.clock.advance(0.6)

        with self.assertRaises(TimeoutError):
            self.send()

        self.assertFalse(self.supervisor.authorized)

    def test_real_adapter_rejected(self):
        class FakeRealAdapter:
            def move(self, **kwargs):
                pass

            def stop(self):
                pass

        with self.assertRaises(TypeError):
            NavigationSupervisor(
                motion=FakeRealAdapter(),
            )


if __name__ == "__main__":
    unittest.main()