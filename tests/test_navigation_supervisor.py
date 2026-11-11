import unittest

from robot.g1pilot_adapter.navigation_bridge import MockMotionAdapter
from robot.g1pilot_adapter.navigation_supervisor import NavigationSupervisor


class FakeClock:
    def __init__(self):
        self.current = 100.0

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += seconds


class TestNavigationSupervisor(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.motion = MockMotionAdapter()
        self.supervisor = NavigationSupervisor(
            motion=self.motion,
            clock=self.clock,
            timeout=0.5,
        )

    def test_disabled_by_default(self):
        self.assertFalse(self.supervisor.authorized)

        with self.assertRaises(RuntimeError):
            self.supervisor.receive_joy(
                axes=[0.0] * 8,
                buttons=[0] * 14,
                created_at=self.clock(),
            )

        self.assertEqual(len(self.motion.commands), 0)

    def test_valid_autonomous_command(self):
        self.supervisor.enable()

        axes = [0.0] * 8
        buttons = [0] * 14

        axes[1] = -0.2
        buttons[8] = 1

        command = self.supervisor.receive_joy(
            axes=axes,
            buttons=buttons,
            created_at=self.clock(),
        )

        self.assertEqual(len(self.motion.commands), 1)
        self.assertGreater(command.vx, 0.0)
        self.assertTrue(self.supervisor.authorized)

    def test_command_timeout(self):
        self.supervisor.enable()

        axes = [0.0] * 8
        buttons = [0] * 14

        axes[1] = -0.2
        buttons[8] = 1

        self.supervisor.receive_joy(
            axes=axes,
            buttons=buttons,
            created_at=self.clock(),
        )

        self.clock.advance(0.6)

        timed_out = self.supervisor.tick()

        self.assertTrue(timed_out)
        self.assertFalse(self.supervisor.authorized)
        self.assertGreaterEqual(self.motion.stop_count, 1)

    def test_stale_command_rejected(self):
        self.supervisor.enable()

        self.clock.advance(0.6)

        with self.assertRaises(TimeoutError):
            self.supervisor.receive_joy(
                axes=[0.0] * 8,
                buttons=[0] * 14,
                created_at=self.clock() - 0.6,
            )

        self.assertFalse(self.supervisor.authorized)
        self.assertEqual(len(self.motion.commands), 0)
        self.assertGreaterEqual(self.motion.stop_count, 1)

    def test_disable_requests_stop(self):
        self.supervisor.enable()
        self.supervisor.disable()

        self.assertFalse(self.supervisor.authorized)
        self.assertEqual(self.motion.stop_count, 1)


if __name__ == "__main__":
    unittest.main()