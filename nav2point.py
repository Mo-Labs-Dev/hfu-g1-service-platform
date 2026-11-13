#!/usr/bin/env python3

import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile

from nav_msgs.msg import Odometry, Path
from sensor_msgs.msg import Joy
from visualization_msgs.msg import Marker
from std_msgs.msg import Bool


def yaw_from_quat(x, y, z, w):
    s = 2.0 * (w * z + x * y)
    c = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(s, c)


def clamp(value, limit):
    return max(-limit, min(limit, value))


class Nav2Point(Node):

    def __init__(self):
        super().__init__("nav2point")

        self.declare_parameter("publish_rate", 50.0)
        self.declare_parameter("pos_kp", 0.8)
        self.declare_parameter("yaw_kp", 1.5)

        self.declare_parameter("waypoint_tolerance", 0.20)
        self.declare_parameter("goal_tolerance", 0.10)

        self.declare_parameter("frame_id", "map")

        self.declare_parameter("joy_topic", "/g1pilot/auto_joy")
        self.declare_parameter("path_topic", "/g1pilot/path")
        self.declare_parameter(
            "auto_enable_topic",
            "/g1pilot/auto_enable",
        )

        self.declare_parameter("vx_limit", 0.05)
        self.declare_parameter("vy_limit", 0.05)
        self.declare_parameter("wz_limit", 0.10)

        self.declare_parameter("odom_timeout", 0.5)
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

        self.frame_id = str(
            self.get_parameter("frame_id").value
        )

        self.joy_topic = str(
            self.get_parameter("joy_topic").value
        )

        self.path_topic = str(
            self.get_parameter("path_topic").value
        )

        self.auto_enable_topic = str(
            self.get_parameter("auto_enable_topic").value
        )

        self.vx_lim = min(
            0.05,
            max(0.001, float(
                self.get_parameter("vx_limit").value
            )),
        )

        self.vy_lim = min(
            0.05,
            max(0.001, float(
                self.get_parameter("vy_limit").value
            )),
        )

        self.wz_lim = min(
            0.10,
            max(0.001, float(
                self.get_parameter("wz_limit").value
            )),
        )

        self.odom_timeout = float(
            self.get_parameter("odom_timeout").value
        )

        self.path_timeout = float(
            self.get_parameter("path_timeout").value
        )

        qos = QoSProfile(depth=10)

        self.sub_odom = self.create_subscription(
            Odometry,
            "/lidar_odometry/pose_fixed",
            self.cb_odom,
            qos,
        )

        self.sub_auto_enable = self.create_subscription(
            Bool,
            self.auto_enable_topic,
            self.cb_auto_enable,
            qos,
        )

        self.sub_path = self.create_subscription(
            Path,
            self.path_topic,
            self.cb_path,
            qos,
        )

        self.pub_joy = self.create_publisher(
            Joy,
            self.joy_topic,
            qos,
        )

        self.pub_wp_marker = self.create_publisher(
            Marker,
            "/g1pilot/waypoint_marker",
            qos,
        )

        self.pub_goal_marker = self.create_publisher(
            Marker,
            "/g1pilot/goal_marker",
            qos,
        )

        self.have_pose = False
        self.last_pose_time = None
        self.last_path_time = None

        self.auto_enabled = False

        self.path = []
        self.path_frame = self.frame_id
        self.idx = 0

        self.x = 0.0
        self.y = 0.0
        self.yaw = 0.0

        self.last_warning = None

        self.timer = self.create_timer(
            1.0 / self.rate,
            self.loop,
        )

        self.get_logger().info(
            "Safe navigation controller initialized. "
            "Automatic navigation disabled."
        )

    def publish_zero(self):
        joy = Joy()
        joy.header.stamp = self.get_clock().now().to_msg()
        joy.axes = [0.0] * 8
        joy.buttons = [0] * 14
        self.pub_joy.publish(joy)

    def warn_once(self, message):
        if self.last_warning != message:
            self.get_logger().warn(message)
            self.last_warning = message

    def cb_odom(self, msg):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation

        values = [
            p.x, p.y,
            q.x, q.y, q.z, q.w,
        ]

        if not all(math.isfinite(v) for v in values):
            self.have_pose = False
            return

        norm = math.sqrt(
            q.x*q.x + q.y*q.y +
            q.z*q.z + q.w*q.w
        )

        if norm < 0.9 or norm > 1.1:
            self.have_pose = False
            return

        self.x = float(p.x)
        self.y = float(p.y)

        self.yaw = yaw_from_quat(
            q.x / norm,
            q.y / norm,
            q.z / norm,
            q.w / norm,
        )

        self.last_pose_time = time.monotonic()
        self.have_pose = True

    def cb_auto_enable(self, msg):
        if not msg.data:
            self.auto_enabled = False
            self.path = []
            self.idx = 0
            self.publish_zero()
            self.get_logger().info(
                "Automatic navigation disabled."
            )
            return

        # An enable request alone is not sufficient
        # to establish physical-motion authorization.
        self.auto_enabled = True
        self.get_logger().info(
            "Navigation requested; validating inputs."
        )

    def cb_path(self, msg):
        if msg.header.frame_id != self.frame_id:
            self.path = []
            self.publish_zero()
            self.warn_once("Rejected path: frame mismatch.")
            return

        if not msg.poses:
            self.path = []
            self.publish_zero()
            self.warn_once("Rejected empty path.")
            return

        points = []

        for pose in msg.poses:
            x = float(pose.pose.position.x)
            y = float(pose.pose.position.y)

            if not math.isfinite(x) or not math.isfinite(y):
                self.path = []
                self.publish_zero()
                self.warn_once(
                    "Rejected path: invalid coordinates."
                )
                return

            points.append((x, y))

        self.path = points
        self.path_frame = msg.header.frame_id
        self.last_path_time = time.monotonic()
        self.idx = 0
        self.last_warning = None

        self.publish_goal_marker(
            self.path[-1][0],
            self.path[-1][1],
        )

    def publish_marker(self, x, y, marker_id, namespace,
                       size, red, green, blue, publisher):
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

        marker.scale.x = size
        marker.scale.y = size
        marker.scale.z = size

        marker.color.r = red
        marker.color.g = green
        marker.color.b = blue
        marker.color.a = 0.9

        publisher.publish(marker)

    def publish_goal_marker(self, gx, gy):
        self.publish_marker(
            gx, gy, 1, "g1pilot_goal",
            0.12, 0.0, 1.0, 0.0,
            self.pub_goal_marker,
        )

    def publish_wp_marker(self, wx, wy):
        self.publish_marker(
            wx, wy, 2, "g1pilot_wp",
            0.10, 1.0, 0.6, 0.0,
            self.pub_wp_marker,
        )

    def loop(self):
        try:
            if not self.auto_enabled:
                self.publish_zero()
                return

            if not self.have_pose or self.last_pose_time is None:
                self.publish_zero()
                self.warn_once("Navigation blocked: no pose.")
                return

            if (
                time.monotonic() - self.last_pose_time
                > self.odom_timeout
            ):
                self.publish_zero()
                self.warn_once(
                    "Navigation blocked: stale odometry."
                )
                return

            if not self.path or self.last_path_time is None:
                self.publish_zero()
                self.warn_once("Navigation blocked: no path.")
                return

            if (
                time.monotonic() - self.last_path_time
                > self.path_timeout
            ):
                self.path = []
                self.publish_zero()
                self.warn_once("Navigation blocked: stale path.")
                return

            if self.idx >= len(self.path):
                self.publish_zero()
                self.warn_once("Navigation path completed.")
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

            dist_goal = math.hypot(
                self.path[-1][0] - self.x,
                self.path[-1][1] - self.y,
            )

            if dist_goal <= self.goal_tol:
                self.publish_zero()
                self.path = []
                self.auto_enabled = False

                self.get_logger().info(
                    "Navigation goal position reached."
                )
                return

            self.publish_wp_marker(wx, wy)

            desired_yaw = math.atan2(dy, dx)

            yaw_err = math.atan2(
                math.sin(desired_yaw - self.yaw),
                math.cos(desired_yaw - self.yaw),
            )

            vx_w = clamp(self.pos_kp * dx, self.vx_lim)
            vy_w = clamp(self.pos_kp * dy, self.vy_lim)

            c = math.cos(self.yaw)
            s = math.sin(self.yaw)

            vx_b = c * vx_w + s * vy_w
            vy_b = -s * vx_w + c * vy_w

            wz = clamp(
                self.yaw_kp * yaw_err,
                self.wz_lim,
            )

            joy = Joy()
            joy.header.stamp = self.get_clock().now().to_msg()

            axes = [0.0] * 8
            buttons = [0] * 14

            axes[1] = clamp(-vx_b / self.vx_lim, 1.0)
            axes[0] = clamp(-vy_b / self.vy_lim, 1.0)
            axes[2] = clamp(-wz / self.wz_lim, 1.0)

            buttons[8] = 1

            joy.axes = axes
            joy.buttons = buttons

            self.pub_joy.publish(joy)
            self.last_warning = None

        except Exception as error:
            self.publish_zero()
            self.get_logger().error(
                f"Navigation controller error: {error}"
            )


def main(args=None):
    rclpy.init(args=args)
    node = Nav2Point()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.publish_zero()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()