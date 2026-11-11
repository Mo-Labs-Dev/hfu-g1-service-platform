#!/usr/bin/env python3

import math
import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    DurabilityPolicy,
    HistoryPolicy,
)

from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from nav_msgs.msg import OccupancyGrid


class MolaOccupancyGrid(Node):

    def __init__(self):
        super().__init__("mola_occupancy_grid")

        # =====================================================
        # MAP CONFIGURATION
        # =====================================================

        self.declare_parameter("resolution", 0.10)
        self.declare_parameter("width", 140)
        self.declare_parameter("height", 140)
        self.declare_parameter("origin_x", -3.0)
        self.declare_parameter("origin_y", -3.0)

        # Height thresholds relative to estimated floor
        self.declare_parameter("ground_tolerance", 0.12)
        self.declare_parameter("obstacle_min_height", 0.18)
        self.declare_parameter("obstacle_max_height", 1.80)

        # Obstacle inflation radius in metres
        self.declare_parameter("inflation_radius", 0.50)

        self.resolution = float(
            self.get_parameter("resolution").value
        )

        self.width = int(
            self.get_parameter("width").value
        )

        self.height = int(
            self.get_parameter("height").value
        )

        self.origin_x = float(
            self.get_parameter("origin_x").value
        )

        self.origin_y = float(
            self.get_parameter("origin_y").value
        )

        self.ground_tolerance = float(
            self.get_parameter("ground_tolerance").value
        )

        self.obstacle_min_height = float(
            self.get_parameter("obstacle_min_height").value
        )

        self.obstacle_max_height = float(
            self.get_parameter("obstacle_max_height").value
        )

        self.inflation_radius = float(
            self.get_parameter("inflation_radius").value
        )

        if (
            self.resolution <= 0
            or self.width <= 0
            or self.height <= 0
            or self.inflation_radius < 0
            or self.ground_tolerance < 0
            or self.obstacle_min_height <= self.ground_tolerance
            or self.obstacle_max_height <= self.obstacle_min_height
        ):
            raise ValueError("Invalid map or height parameters")

        # =====================================================
        # ROS2 QOS CONFIGURATION
        # =====================================================

        # MOLA publishes its map with TRANSIENT_LOCAL QoS.
        cloud_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        # Publish occupancy grid for Dijkstra
        self.map_publisher = self.create_publisher(
            OccupancyGrid,
            "/map",
            map_qos,
        )

        # Subscribe to actual MOLA 3D map
        self.cloud_subscriber = self.create_subscription(
            PointCloud2,
            "/lidar_odometry/localmap_points",
            self.cloud_callback,
            cloud_qos,
        )

        self.get_logger().info(
            "MOLA occupancy converter started. "
            "Waiting for point cloud..."
        )

    # =========================================================
    # OBSTACLE INFLATION
    # =========================================================

    def inflate_obstacles(self, obstacles):

        radius_cells = int(
            math.ceil(
                self.inflation_radius / self.resolution
            )
        )

        inflated = obstacles.copy()

        if radius_cells == 0:
            return inflated

        occupied_y, occupied_x = np.nonzero(obstacles)

        offsets = []

        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):

                distance = (
                    math.hypot(dx, dy) * self.resolution
                )

                if distance <= self.inflation_radius:
                    offsets.append((dx, dy))

        for dx, dy in offsets:

            nx = occupied_x + dx
            ny = occupied_y + dy

            valid = (
                (nx >= 0)
                & (nx < self.width)
                & (ny >= 0)
                & (ny < self.height)
            )

            inflated[
                ny[valid],
                nx[valid]
            ] = True

        return inflated

    # =========================================================
    # MOLA POINT CLOUD CALLBACK
    # =========================================================

    def cloud_callback(self, msg):

        # The saved G1 destinations use the map frame.
        if msg.header.frame_id != "map":

            self.get_logger().error(
                "Point cloud is not in map frame. "
                "Refusing to publish occupancy grid."
            )
            return

        try:

            # =================================================
            # STEP 1: READ MOLA XYZ POINTS
            # =================================================

            # ROS2 Humble may return a structured NumPy array:
            #
            # dtype=[
            #   ('x', '<f4'),
            #   ('y', '<f4'),
            #   ('z', '<f4')
            # ]
            #
            # Extract each field separately.

            cloud = point_cloud2.read_points(
                msg,
                field_names=("x", "y", "z"),
                skip_nans=True,
            )

            if len(cloud) == 0:

                self.get_logger().warning(
                    "Received empty point cloud"
                )
                return

            # Convert structured XYZ fields into Nx3 float32.
            points = np.column_stack(
                (
                    cloud["x"],
                    cloud["y"],
                    cloud["z"],
                )
            ).astype(np.float32)

            finite = np.isfinite(points).all(axis=1)
            points = points[finite]

            if len(points) < 100:

                self.get_logger().warning(
                    "Too few valid map points"
                )
                return

            # =================================================
            # STEP 2: ESTIMATE FLOOR HEIGHT
            # =================================================

            # Preliminary estimate only.
            # Must be validated against the real lab floor.

            floor_z = float(
                np.percentile(points[:, 2], 10)
            )

            x = points[:, 0]
            y = points[:, 1]

            z_relative = (
                points[:, 2] - floor_z
            )

            # =================================================
            # STEP 3: WORLD COORDINATES -> GRID COORDINATES
            # =================================================

            gx = np.floor(
                (x - self.origin_x) / self.resolution
            ).astype(np.int32)

            gy = np.floor(
                (y - self.origin_y) / self.resolution
            ).astype(np.int32)

            inside = (
                (gx >= 0)
                & (gx < self.width)
                & (gy >= 0)
                & (gy < self.height)
            )

            gx = gx[inside]
            gy = gy[inside]
            z_relative = z_relative[inside]

            # =================================================
            # STEP 4: CREATE OCCUPANCY GRID
            # =================================================

            # ROS occupancy values:
            #
            # -1  = unknown
            #  0  = observed ground (candidate free space)
            # 100 = obstacle

            grid = np.full(
                (self.height, self.width),
                -1,
                dtype=np.int8,
            )

            ground = (
                np.abs(z_relative)
                <= self.ground_tolerance
            )

            obstacles = (
                (z_relative >= self.obstacle_min_height)
                & (z_relative <= self.obstacle_max_height)
            )

            # Mark observed ground cells.
            grid[
                gy[ground],
                gx[ground]
            ] = 0

            # =================================================
            # STEP 5: CREATE OBSTACLE MASK
            # =================================================

            obstacle_grid = np.zeros(
                (self.height, self.width),
                dtype=bool,
            )

            obstacle_grid[
                gy[obstacles],
                gx[obstacles]
            ] = True

            # =================================================
            # STEP 6: INFLATE OBSTACLES
            # =================================================

            inflated = self.inflate_obstacles(
                obstacle_grid
            )

            # Obstacles override ground observations.
            grid[inflated] = 100

            # =================================================
            # STEP 7: PUBLISH ROS2 OCCUPANCY GRID
            # =================================================

            occupancy_msg = OccupancyGrid()

            occupancy_msg.header.stamp = (
                self.get_clock().now().to_msg()
            )

            occupancy_msg.header.frame_id = "map"

            occupancy_msg.info.resolution = self.resolution
            occupancy_msg.info.width = self.width
            occupancy_msg.info.height = self.height

            occupancy_msg.info.origin.position.x = (
                self.origin_x
            )

            occupancy_msg.info.origin.position.y = (
                self.origin_y
            )

            occupancy_msg.info.origin.orientation.w = 1.0

            occupancy_msg.data = (
                grid.flatten().tolist()
            )

            self.map_publisher.publish(
                occupancy_msg
            )

            # =================================================
            # STEP 8: REPORT RESULTS
            # =================================================

            free_cells = int(
                np.count_nonzero(grid == 0)
            )

            occupied_cells = int(
                np.count_nonzero(grid == 100)
            )

            unknown_cells = int(
                np.count_nonzero(grid == -1)
            )

            self.get_logger().info(
                f"Map published | "
                f"points={len(points)} | "
                f"estimated_floor_z={floor_z:.2f} | "
                f"free={free_cells} | "
                f"occupied={occupied_cells} | "
                f"unknown={unknown_cells}"
            )

        except Exception as error:

            self.get_logger().error(
                f"Map conversion failed: {error}"
            )


# =============================================================
# MAIN
# =============================================================

def main(args=None):

    rclpy.init(args=args)

    node = MolaOccupancyGrid()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()