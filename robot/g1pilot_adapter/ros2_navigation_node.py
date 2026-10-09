#!/usr/bin/env python3
from __future__ import annotations

import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Bool

from robot.g1pilot_adapter.navigation_bridge import MockMotionAdapter
from robot.g1pilot_adapter.navigation_supervisor import NavigationSupervisor


class ROS2NavigationMockNode(Node):
    """
    ROS 2 mock navigation subscriber.

    Uses MockMotionAdapter only.
    Does not connect to physical robot hardware.
    """

    def __init__(self):
        super().__init__("hfu_navigation_mock")

        self.motion = MockMotionAdapter()

        self.supervisor = NavigationSupervisor(
            motion=self.motion,
            clock=time.monotonic,
            timeout=0.5,
        )

        self.sub_joy = self.create_subscription(
            Joy,
            "/g1pilot/auto_joy",
            self.on_joy,
            10,
        )

        # Separate test authorization topic.
        # This does not authorize physical robot motion.
        self.sub_enable = self.create_subscription(
            Bool,
            "/hfu/mock_navigation_enable",
            self.on_enable,
            10,
        )

        self.timer = self.create_timer(
            0.05,
            self.check_timeout,
        )

        self.get_logger().info(
            "HFU ROS 2 navigation MOCK node started. "
            "Physical movement disabled."
        )

    def on_enable(self, msg: Bool):
        if msg.data:
            self.supervisor.enable()
            self.get_logger().info("Mock navigation enabled")
        else:
            self.supervisor.disable()
            self.get_logger().info("Mock navigation disabled")

    def on_joy(self, msg: Joy):
        if not self.supervisor.authorized:
            return

        # Receipt time is used for now. ROS header timestamps
        # are not yet verified against a common clock.
        received_at = time.monotonic()

        try:
            command = self.supervisor.receive_joy(
                axes=msg.axes,
                buttons=msg.buttons,
                created_at=received_at,
            )

            self.get_logger().info(
                f"MOCK vx={command.vx:.3f}, "
                f"vy={command.vy:.3f}, "
                f"yaw={command.yaw:.3f}"
            )

        except Exception as error:
            self.get_logger().error(
                f"Mock navigation rejected: {error}"
            )

    def check_timeout(self):
        if self.supervisor.tick():
            self.get_logger().warn(
                "Navigation command timeout. Mock stop requested."
            )


def main(args=None):
    rclpy.init(args=args)
    node = ROS2NavigationMockNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.supervisor.disable()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()