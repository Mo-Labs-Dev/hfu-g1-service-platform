#!/usr/bin/env python3
from __future__ import annotations

import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import Joy
from visualization_msgs.msg import Marker
from std_msgs.msg import Bool

from robot.g1pilot_adapter.navigation_safety_policy import (
    NavigationSafetyPolicy,
    NavigationSafetyConfig,
)


def clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def yaw_from_quat(x, y, z, w):
    return math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )


class Nav2Point(Node):
    """
    Safety-gated G1Pilot navigation controller.

    IMPORTANT:
    This controller publishes Joy messages only.
    It does not connect to the Unitree SDK.

    Physical locomotion integration remains disabled.
    """

    def __init__(self):
        super().__init__("nav2point_safe")

        self.declare_parameter("publish_rate", 50.0)
        self.declare_parameter("pos_kp", 0.8)
        self.declare_parameter("yaw_kp", 1.5)

        self.declare_parameter("waypoint_tolerance", 0.20)
        self.declare_parameter("goal_tolerance", 0.10)

        self.declare_parameter("frame_id", "map")
        self.declare_parameter("joy_topic", "/hfu/nav_safe_joy")
        self.declare_parameter("path_topic", "/g1pilot/path")
        self.declare_parameter(
            "odom_topic", "/lidar_odometry/pose_fixed"
        )
        self.declare_parameter(
            "auto_enable_topic", "/hfu/nav_safe_enable"
        )

        self.declare_parameter("vx_limit", 0.20)
        self.declare_parameter("vy_limit", 0.10)
        self.declare_parameter("wz_limit", 0.20)

        self.declare_parameter("odometry_timeout", 0.5)
        self.declare_parameter("path_timeout", 2.0)

        self.rate = float(
            self.get_parameter("publish_rate").value
        )
        self.pos_kp = float(
            self.get_parameter("pos_kp").value
        )
        self.yaw_kp = float(
            self.get_parameter("yaw_kp").value
        )

        self.wp_tol = float(
            self.get_parameter("waypoint_tolerance").value
        )
        self.goal_tol = float(
            self.get_parameter("goal_tolerance").value
        )

        self.frame_id = self.get_parameter("frame_id").value
        self.joy_topic = self.get_parameter("joy_topic").value
        self.path_topic = self.get_parameter("path_topic").value
        self.odom_topic = self.get_parameter("odom_topic").value
        self.auto_enable_topic = self.get_parameter(
            "auto_enable_topic"
        ).value

        self.vx_lim = float(
            self.get_parameter("vx_limit").value
        )
        self.vy_lim = float(
            self.get_parameter("vy_limit").value
        )
        self.wz_lim = float(
            self.get_parameter("wz_limit").value
        )

        self.odom_timeout = float(
            self.get_parameter("odometry_timeout").value
        )
        self.path_timeout = float(
            self.get_parameter("path_timeout").value
        )

        numeric_parameters = (
            self.rate,
            self.pos_kp,
            self.yaw_kp,
            self.wp_tol,
            self.goal_tol,
            self.vx_lim,
            self.vy_lim,
            self.wz_lim,
            self.odom_timeout,
            self.path_timeout,
        )

        if not all(
            math.isfinite(v) and v > 0
            for v in numeric_parameters
        ):
            raise ValueError(
                "Navigation parameters must be finite and positive"
            )

        self.safety_config = NavigationSafetyConfig(
            odometry_timeout=self.odom_timeout,
            path_timeout=self.path_timeout,
        )

        self.safety = self._new_safety_policy()

        qos = QoSProfile(depth=10)

        self.sub_odom = self.create_subscription(
            Odometry,
            self.odom_topic,
            self.cb_odom,
            qos,
        )

        self.sub_path = self.create_subscription(
            Path,
            self.path_topic,
            self.cb_path,
            qos,
        )

        self.sub_enable = self.create_subscription(
            Bool,
            self.auto_enable_topic,
            self.cb_auto_enable,
            qos,
        )

        self.pub_joy = self.create_publisher(
            Joy,
            self.joy_topic,
            qos,
        )

        self.pub_wp_marker = self.create_publisher(
            Marker,
            "/hfu/safe_waypoint_marker",
            qos,
        )

        self.pub_goal_marker = self.create_publisher(
            Marker,
            "/hfu/safe_goal_marker",
            qos,
        )

        self.x = 0.0
        self.y = 0.0
        self.yaw = 0.0
        self.odom_frame = ""

        self.path = []
        self.path_frame = self.frame_id
        self.idx = 0

        self.auto_enabled = False
        self.goal_reached = False
        self.stop_reason = None

        self.timer = self.create_timer(
            1.0 / self.rate,
            self.loop,
        )

        self.get_logger().info(
            "Safe navigation controller initialized. "
            "AUTONOMOUS NAVIGATION DISABLED."
        )

    def _new_safety_policy(self):
        return NavigationSafetyPolicy(
            config=self.safety_config,
            clock=time.monotonic,
        )

    def publish_zero(self):
        joy = Joy()
        joy.header.stamp = self.get_clock().now().to_msg()
        joy.axes = [0.0] * 8
        joy.buttons = [0] * 14
        self.pub_joy.publish(joy)

    def halt(self, reason: str):
        self.publish_zero()

        if self.stop_reason != reason:
            self.get_logger().warn(
                f"Navigation stopped: {reason}"
            )
            self.stop_reason = reason

    def cb_auto_enable(self, msg: Bool):
        if not msg.data:
            self.auto_enabled = False
            self.safety.disable()
            self.path = []
            self.idx = 0
            self.goal_reached = False

            self.halt("Autonomous navigation disabled")
            return

        if self.auto_enabled:
            return

        # Require fresh localization and a newly received path
        # each time navigation is enabled.
        self.safety = self._new_safety_policy()
        self.safety.enable()

        self.auto_enabled = True
        self.path = []
        self.idx = 0
        self.goal_reached = False
        self.stop_reason = None

        self.get_logger().info(
            "Navigation enabled. Waiting for fresh pose and path."
        )

    def cb_odom(self, msg: Odometry):
        if not self.auto_enabled:
            return

        try:
            x = float(msg.pose.pose.position.x)
            y = float(msg.pose.pose.position.y)

            orientation = msg.pose.pose.orientation
            quaternion = (
                float(orientation.x),
                float(orientation.y),
                float(orientation.z),
                float(orientation.w),
            )

            if not all(math.isfinite(v) for v in quaternion):
                raise ValueError("Invalid quaternion")

            norm = math.sqrt(sum(v * v for v in quaternion))

            if norm < 1e-8:
                raise ValueError("Zero-length quaternion")

            qx, qy, qz, qw = (
                value / norm for value in quaternion
            )

            yaw = yaw_from_quat(qx, qy, qz, qw)

            frame = msg.header.frame_id.strip()

            if not frame:
                raise ValueError("Missing odometry frame")

            if not self.safety.update_odometry(x, y, yaw):
                raise ValueError("Invalid odometry position")

            self.x = x
            self.y = y
            self.yaw = yaw
            self.odom_frame = frame

            # Revalidate the active path when the odometry
            # reference frame changes.
            if self.path and self.path_frame != frame:
                self.safety.update_path(
                    self.path,
                    self.path_frame,
                    frame,
                )

        except Exception as error:
            self.safety.pose_valid = False
            self.safety.last_odom = None
            self.halt(f"Invalid odometry: {error}")

    def cb_path(self, msg: Path):
        if not self.auto_enabled:
            return

        try:
            frame = msg.header.frame_id.strip()
            points = [
                (
                    float(p.pose.position.x),
                    float(p.pose.position.y),
                )
                for p in msg.poses
            ]

            valid = self.safety.update_path(
                points,
                frame,
                self.odom_frame,
            )

            if not valid:
                self.path = []
                self.idx = 0
                self.halt("Invalid path or reference frame")
                return

            self.path = points
            self.path_frame = frame
            self.idx = 0
            self.goal_reached = False
            self.stop_reason = None

            self.publish_goal_marker(
                self.path[-1][0],
                self.path[-1][1],
            )

            self.get_logger().info(
                f"Accepted path with {len(points)} points"
            )

        except Exception as error:
            self.path = []
            self.idx = 0
            self.safety.path_valid = False
            self.safety.last_path = None
            self.halt(f"Invalid path: {error}")

    def publish_marker(self, x, y, marker_id, namespace, color):
        marker = Marker()

        marker.header.frame_id = self.path_frame
        marker.header.stamp = self.get_clock().now().to_msg()

        marker.ns = namespace
        marker.id = marker_id
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD

        marker.pose.position.x = float(x)
        marker.pose.position.y = float(y)
        marker.pose.orientation.w = 1.0

        marker.scale.x = 0.12
        marker.scale.y = 0.12
        marker.scale.z = 0.12

        marker.color.r = color[0]
        marker.color.g = color[1]
        marker.color.b = color[2]
        marker.color.a = 0.9

        if marker_id == 2:
            self.pub_wp_marker.publish(marker)
        else:
            self.pub_goal_marker.publish(marker)

    def publish_goal_marker(self, x, y):
        self.publish_marker(
            x, y, 1, "hfu_safe_goal", (0.0, 1.0, 0.0)
        )

    def publish_wp_marker(self, x, y):
        self.publish_marker(
            x, y, 2, "hfu_safe_waypoint", (1.0, 0.6, 0.0)
        )

    def loop(self):
        try:
            # Always publish zero commands when not enabled.
            if not self.auto_enabled:
                self.publish_zero()
                return

            if self.goal_reached:
                self.publish_zero()
                return

            if not self.safety.can_move():
                self.halt(
                    "Safety gate blocked: missing, invalid, "
                    "or expired localization/path"
                )
                return

            if not self.path or self.idx >= len(self.path):
                self.halt("No valid active waypoint")
                return

            wx, wy = self.path[self.idx]

            dx = wx - self.x
            dy = wy - self.y

            dist_wp = math.hypot(dx, dy)

            if (
                self.idx < len(self.path) - 1
                and dist_wp <= self.wp_tol
            ):
                self.idx += 1

                wx, wy = self.path[self.idx]
                dx = wx - self.x
                dy = wy - self.y

            self.publish_wp_marker(wx, wy)

            gx, gy = self.path[-1]
            dist_goal = math.hypot(
                gx - self.x,
                gy - self.y,
            )

            if dist_goal <= self.goal_tol:
                self.goal_reached = True
                self.auto_enabled = False
                self.safety.disable()
                self.path = []

                self.publish_zero()

                self.get_logger().info(
                    "Navigation goal reached."
                )
                return

            desired_yaw = math.atan2(dy, dx)

            yaw_error = math.atan2(
                math.sin(desired_yaw - self.yaw),
                math.cos(desired_yaw - self.yaw),
            )

            vx_world = clamp(
                self.pos_kp * dx,
                self.vx_lim,
            )

            vy_world = clamp(
                self.pos_kp * dy,
                self.vy_lim,
            )

            c = math.cos(-self.yaw)
            s = math.sin(-self.yaw)

            vx_body = (
                c * vx_world - s * vy_world
            )

            vy_body = (
                s * vx_world + c * vy_world
            )

            wz = clamp(
                self.yaw_kp * yaw_error,
                self.wz_lim,
            )

            # Keep G1Pilot's original joystick sign convention.
            ax1 = clamp(
                -vx_body / self.vx_lim,
                1.0,
            )

            ax0 = clamp(
                -vy_body / self.vy_lim,
                1.0,
            )

            ax2 = clamp(
                -wz / self.wz_lim,
                1.0,
            )

            joy = Joy()
            joy.header.stamp = self.get_clock().now().to_msg()

            joy.axes = [0.0] * 8
            joy.buttons = [0] * 14

            joy.axes[1] = ax1
            joy.axes[0] = ax0
            joy.axes[2] = ax2

            joy.buttons[8] = 1

            self.pub_joy.publish(joy)
            self.stop_reason = None

        except Exception as error:
            self.auto_enabled = False
            self.safety.disable()
            self.path = []
            self.halt(f"Navigation controller error: {error}")


def main(args=None):
    rclpy.init(args=args)
    node = Nav2Point()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.auto_enabled = False
        node.safety.disable()
        node.publish_zero()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()