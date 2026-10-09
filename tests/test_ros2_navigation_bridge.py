import unittest

from robot.g1pilot_adapter.ros2_navigation_bridge import (
    G1PilotJoyConverter,
)


class JoyConverterTests(unittest.TestCase):

    def setUp(self):
        self.converter = G1PilotJoyConverter()

    def test_disabled_means_zero(self):
        axes = [0.0] * 8
        axes[1] = -1.0
        buttons = [0] * 14
        buttons[8] = 1

        result = self.converter.convert(
            axes, buttons, enabled=False
        )

        self.assertEqual(result.vx, 0.0)

    def test_forward_conversion(self):
        axes = [0.0] * 8
        axes[1] = -0.4
        buttons = [0] * 14
        buttons[8] = 1

        result = self.converter.convert(
            axes, buttons, enabled=True
        )

        self.assertAlmostEqual(result.vx, 0.2)

    def test_lateral_conversion(self):
        axes = [0.0] * 8
        axes[0] = -0.2
        buttons = [0] * 14
        buttons[8] = 1

        result = self.converter.convert(
            axes, buttons, enabled=True
        )

        self.assertAlmostEqual(result.vy, 0.1)

    def test_rotation_conversion(self):
        axes = [0.0] * 8
        axes[2] = -0.4
        buttons = [0] * 14
        buttons[8] = 1

        result = self.converter.convert(
            axes, buttons, enabled=True
        )

        self.assertAlmostEqual(result.yaw, 0.2)

    def test_button_released(self):
        axes = [0.0] * 8
        axes[1] = -1.0
        buttons = [0] * 14

        result = self.converter.convert(
            axes, buttons, enabled=True
        )

        self.assertEqual(result.vx, 0.0)

    def test_invalid_message(self):
        with self.assertRaises(ValueError):
            self.converter.convert(
                [0.0],
                [1],
                enabled=True,
            )

    def test_nan_rejected(self):
        axes = [0.0] * 8
        axes[1] = float("nan")
        buttons = [0] * 14
        buttons[8] = 1

        with self.assertRaises(ValueError):
            self.converter.convert(
                axes, buttons, enabled=True
            )


if __name__ == "__main__":
    unittest.main()