import time
import unittest

from g1_walk_safety import G1WalkSafety


class TestG1WalkSafety(unittest.TestCase):

    def setUp(self):
        self.commands = []
        self.controller = G1WalkSafety(
            lambda vx, vy, yaw: self.commands.append(
                (vx, vy, yaw)
            )
        )

    def test_arm_requires_confirmation(self):
        self.assertFalse(self.controller.arm(False))
        self.assertTrue(self.controller.arm(True))

    def test_velocity_limits(self):
        self.controller.arm(True)

        with self.assertRaises(ValueError):
            self.controller.command(0.5, 0.0, 0.0)

        self.assertEqual(self.commands, [])

    def test_walking_command(self):
        self.controller.arm(True)
        self.controller.command(0.05, 0.0, 0.0)

        self.assertEqual(
            self.commands[-1],
            (0.05, 0.0, 0.0)
        )

    def test_manual_stop(self):
        self.controller.arm(True)
        self.controller.command(0.05, 0.0, 0.0)
        self.controller.stop()

        self.assertEqual(
            self.commands[-1],
            (0.0, 0.0, 0.0)
        )
        self.assertFalse(self.controller.armed)

    def test_watchdog_timeout(self):
        self.controller.COMMAND_TIMEOUT = 0.05
        self.controller.arm(True)

        import threading
        threading.Thread(
            target=self.controller.watchdog,
            daemon=True
        ).start()

        self.controller.command(0.05, 0.0, 0.0)
        time.sleep(0.15)

        self.assertTrue(self.controller.fault)
        self.assertFalse(self.controller.armed)
        self.assertEqual(
            self.commands[-1],
            (0.0, 0.0, 0.0)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
