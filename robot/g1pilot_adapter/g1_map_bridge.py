#!/usr/bin/env python3

from __future__ import annotations

import heapq
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2


# ============================================================
# G1 STUDIO - MOLA MAP BRIDGE
#
# Read-only ROS2 -> HTTP bridge.
#
# Endpoints:
#   GET /status
#   GET /pose
#   GET /map
#   GET /plan?x=...&y=...&frame_id=map
#   GET /floor-diagnostics
#   GET /occupancy-grid
#
# Floor detection is diagnostic only.
# Physical robot motion is never commanded here.
# ============================================================

HOST = "0.0.0.0"
PORT = 8769

MAP_TOPIC = "/lidar_odometry/localmap_points"
POSE_TOPIC = "/lidar_odometry/pose"

MAX_MAP_POINTS = 100000
POSE_TIMEOUT = 5.0

# Existing experimental A* settings.
RESOLUTION = 0.10
GRID_PADDING = 1.0
MAX_GRID_CELLS = 500000

FLOOR_BAND = 0.15
OBSTACLE_MIN_HEIGHT = 0.20
OBSTACLE_MAX_HEIGHT = 1.80

MIN_FLOOR_POINTS_PER_CELL = 2
MIN_OBSTACLE_POINTS_PER_CELL = 2
CLEARANCE_RADIUS = 0.45

MAX_ENDPOINT_DISTANCE = 0.35
MAX_ROUTE_NODES = 100000

# New RANSAC diagnostics settings.
RANSAC_ITERATIONS = 400
RANSAC_DISTANCE_THRESHOLD = 0.08
RANSAC_MAX_TILT_DEGREES = 12.0
RANSAC_MAX_CANDIDATES = 4
RANSAC_MIN_INLIERS = 80
RANSAC_MIN_INLIER_RATIO = 0.01

NEAR_ROBOT_RADIUS = 1.0
DIAGNOSTIC_GRID_RESOLUTION = 0.25

_lock = threading.Lock()

_latest_pose = None
_pose_received = None

_latest_map = None
_map_received = None
_latest_xyz = None

_map_version = 0

_floor_cache_version = -1
_floor_cache = None
_floor_compute_lock = threading.Lock()


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def age_seconds(received):
    if received is None:
        return None

    return time.monotonic() - received


def normalized_plane(normal, offset):
    magnitude = float(np.linalg.norm(normal))

    if magnitude < 1e-9:
        return None

    normal = normal / magnitude
    offset = float(offset / magnitude)

    # Keep the normal pointing toward positive Z.
    if normal[2] < 0:
        normal = -normal
        offset = -offset

    return normal, offset


def fit_plane_svd(points):
    if len(points) < 3:
        return None

    center = points.mean(axis=0)

    centered = points - center

    try:
        _, _, vh = np.linalg.svd(
            centered,
            full_matrices=False,
        )
    except np.linalg.LinAlgError:
        return None

    normal = vh[-1]
    offset = -float(np.dot(normal, center))

    return normalized_plane(normal, offset)


def plane_tilt_degrees(normal):
    z_component = float(
        np.clip(normal[2], -1.0, 1.0)
    )

    return math.degrees(
        math.acos(z_component)
    )


def plane_z_at(normal, offset, x, y):
    if abs(float(normal[2])) < 1e-8:
        return None

    return float(
        -(
            normal[0] * x
            + normal[1] * y
            + offset
        ) / normal[2]
    )


def grid_coverage(points):
    """
    Count occupied XY bins for diagnostics only.

    This does not establish free space or connectivity.
    """
    if len(points) == 0:
        return 0

    xy_cells = np.floor(
        points[:, :2] / DIAGNOSTIC_GRID_RESOLUTION
    ).astype(np.int32)

    return int(
        len(np.unique(xy_cells, axis=0))
    )


def detect_floor_candidates(points, robot_position):
    """
    Detect approximately horizontal planes using RANSAC.

    Candidates may be floors, tables, shelves, or other
    surfaces. No candidate is automatically approved.
    """

    if points is None or len(points) < 100:
        return {
            "success": False,
            "reason": "Insufficient point-cloud data",
            "candidates": [],
        }

    points = np.asarray(
        points,
        dtype=np.float64,
    )

    finite_mask = np.isfinite(points).all(axis=1)
    points = points[finite_mask]

    if len(points) < 100:
        return {
            "success": False,
            "reason": "Insufficient finite points",
            "candidates": [],
        }

    rng = np.random.default_rng(42)

    remaining = points.copy()
    candidates = []

    minimum_inliers = max(
        RANSAC_MIN_INLIERS,
        int(
            len(points)
            * RANSAC_MIN_INLIER_RATIO
        ),
    )

    robot_x = float(robot_position["x"])
    robot_y = float(robot_position["y"])
    robot_z = float(robot_position["z"])

    for candidate_index in range(
        RANSAC_MAX_CANDIDATES
    ):
        if len(remaining) < minimum_inliers:
            break

        best_mask = None
        best_count = 0

        for _ in range(RANSAC_ITERATIONS):
            indices = rng.choice(
                len(remaining),
                size=3,
                replace=False,
            )

            p1, p2, p3 = remaining[indices]

            normal = np.cross(
                p2 - p1,
                p3 - p1,
            )

            plane = normalized_plane(
                normal,
                -float(np.dot(normal, p1)),
            )

            if plane is None:
                continue

            normal, offset = plane

            tilt = plane_tilt_degrees(normal)

            if tilt > RANSAC_MAX_TILT_DEGREES:
                continue

            distances = np.abs(
                remaining @ normal + offset
            )

            inlier_mask = (
                distances
                <= RANSAC_DISTANCE_THRESHOLD
            )

            count = int(inlier_mask.sum())

            if count > best_count:
                best_count = count
                best_mask = inlier_mask

        if (
            best_mask is None
            or best_count < minimum_inliers
        ):
            break

        inlier_points = remaining[best_mask]

        refined = fit_plane_svd(inlier_points)

        if refined is None:
            break

        normal, offset = refined

        if (
            plane_tilt_degrees(normal)
            > RANSAC_MAX_TILT_DEGREES
        ):
            break

        # Recompute support using the refined plane.
        distances = np.abs(
            remaining @ normal + offset
        )

        refined_mask = (
            distances
            <= RANSAC_DISTANCE_THRESHOLD
        )

        support = remaining[refined_mask]

        if len(support) < minimum_inliers:
            break

        predicted_z = plane_z_at(
            normal,
            offset,
            robot_x,
            robot_y,
        )

        horizontal_distance = np.hypot(
            support[:, 0] - robot_x,
            support[:, 1] - robot_y,
        )

        nearby_support = support[
            horizontal_distance <= NEAR_ROBOT_RADIUS
        ]

        x_min = float(support[:, 0].min())
        x_max = float(support[:, 0].max())

        y_min = float(support[:, 1].min())
        y_max = float(support[:, 1].max())

        candidate = {
            "id": candidate_index + 1,
            "normal": [
                float(value)
                for value in normal
            ],
            "plane_offset": float(offset),
            "tilt_degrees": round(
                plane_tilt_degrees(normal),
                3,
            ),
            "inlier_count": int(len(support)),
            "inlier_ratio": round(
                len(support) / len(points),
                4,
            ),
            "z_at_robot_xy": predicted_z,
            "robot_z_minus_plane_z": (
                float(robot_z - predicted_z)
                if predicted_z is not None
                else None
            ),
            "near_robot_inlier_count": int(
                len(nearby_support)
            ),
            "xy_bounds": {
                "min_x": x_min,
                "max_x": x_max,
                "min_y": y_min,
                "max_y": y_max,
            },
            "xy_span_m": {
                "x": round(x_max - x_min, 3),
                "y": round(y_max - y_min, 3),
            },
            "support_grid_cells": grid_coverage(
                support
            ),
            "near_robot_grid_cells": grid_coverage(
                nearby_support
            ),
            "classification": "unverified_horizontal_surface",
            "approved_for_navigation": False,
        }

        candidates.append(candidate)

        # Remove this plane's support before searching
        # for additional horizontal surfaces.
        remaining = remaining[~refined_mask]

    return {
        "success": len(candidates) > 0,
        "method": "horizontal_plane_ransac",
        "diagnostic_only": True,
        "point_count": int(len(points)),
        "candidate_count": len(candidates),
        "parameters": {
            "iterations": RANSAC_ITERATIONS,
            "distance_threshold_m": (
                RANSAC_DISTANCE_THRESHOLD
            ),
            "maximum_tilt_degrees": (
                RANSAC_MAX_TILT_DEGREES
            ),
            "near_robot_radius_m": (
                NEAR_ROBOT_RADIUS
            ),
            "coverage_cell_size_m": (
                DIAGNOSTIC_GRID_RESOLUTION
            ),
        },
        "candidates": candidates,
        "warnings": [
            "Detected horizontal planes are not necessarily floors.",
            "A tabletop may produce a stronger plane than the floor.",
            "The map frame's gravity alignment is not independently verified.",
            "Point-cloud support does not establish traversability.",
            "No candidate is approved for physical robot navigation.",
        ],
    }


class G1MapBridge(Node):
    def __init__(self):
        super().__init__(
            "g1_studio_map_bridge"
        )

        pose_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )

        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.pose_subscription = (
            self.create_subscription(
                Odometry,
                POSE_TOPIC,
                self.on_pose,
                pose_qos,
            )
        )

        self.map_subscription = (
            self.create_subscription(
                PointCloud2,
                MAP_TOPIC,
                self.on_map,
                map_qos,
            )
        )

        self.get_logger().info(
            f"Subscribed to pose: {POSE_TOPIC}"
        )

        self.get_logger().info(
            f"Subscribed to map: {MAP_TOPIC}"
        )

    def on_pose(self, msg):
        global _latest_pose, _pose_received

        p = msg.pose.pose.position
        q = msg.pose.pose.orientation

        siny = 2.0 * (
            q.w * q.z + q.x * q.y
        )

        cosy = 1.0 - 2.0 * (
            q.y * q.y + q.z * q.z
        )

        yaw = math.atan2(siny, cosy)

        payload = {
            "frame_id": msg.header.frame_id,
            "child_frame_id": msg.child_frame_id,
            "position": {
                "x": float(p.x),
                "y": float(p.y),
                "z": float(p.z),
            },
            "orientation": {
                "x": float(q.x),
                "y": float(q.y),
                "z": float(q.z),
                "w": float(q.w),
            },
            "yaw": float(yaw),
        }

        with _lock:
            _latest_pose = payload
            _pose_received = time.monotonic()

    def on_map(self, msg):
        global _latest_map
        global _map_received
        global _latest_xyz
        global _map_version
        global _floor_cache_version
        global _floor_cache

        try:
            total = int(
                msg.width * msg.height
            )

            if total <= 0:
                return

            stride = max(
                1,
                math.ceil(
                    total / MAX_MAP_POINTS
                ),
            )

            points = []

            for index, point in enumerate(
                point_cloud2.read_points(
                    msg,
                    field_names=("x", "y", "z"),
                    skip_nans=True,
                )
            ):
                if index % stride != 0:
                    continue

                xyz = [
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                ]

                if all(
                    math.isfinite(value)
                    for value in xyz
                ):
                    points.append(xyz)

            if not points:
                return

            array = np.asarray(
                points,
                dtype=np.float32,
            )

            payload = {
                "connected": True,
                "source": MAP_TOPIC,
                "frame_id": msg.header.frame_id,
                "total_points": total,
                "displayed_points": len(points),
                "points": points,
            }

            with _lock:
                _latest_map = payload
                _latest_xyz = array
                _map_received = time.monotonic()
                _map_version += 1
                _floor_cache_version = -1
                _floor_cache = None

            self.get_logger().info(
                f"MOLA map received: {len(points)} points"
            )

        except Exception as error:
            self.get_logger().error(
                f"Map processing error: {error}"
            )


def build_occupancy(points, start, goal):
    """
    Existing experimental occupancy construction.

    IMPORTANT:
    This still uses the original 10th-percentile
    floor estimate. RANSAC diagnostics do not
    automatically change the planner.
    """

    if len(points) < 100:
        raise ValueError(
            "Insufficient MOLA map points"
        )

    xs = points[:, 0]
    ys = points[:, 1]
    zs = points[:, 2]

    min_x = float(
        min(xs.min(), start[0], goal[0])
        - GRID_PADDING
    )

    max_x = float(
        max(xs.max(), start[0], goal[0])
        + GRID_PADDING
    )

    min_y = float(
        min(ys.min(), start[1], goal[1])
        - GRID_PADDING
    )

    max_y = float(
        max(ys.max(), start[1], goal[1])
        + GRID_PADDING
    )

    width = math.ceil(
        (max_x - min_x) / RESOLUTION
    ) + 1

    height = math.ceil(
        (max_y - min_y) / RESOLUTION
    ) + 1

    if width * height > MAX_GRID_CELLS:
        raise ValueError(
            "Map exceeds planning grid limit"
        )

    floor_z = float(
        np.percentile(zs, 10)
    )

    floor_mask = (
        np.abs(zs - floor_z) <= FLOOR_BAND
    )

    obstacle_mask = (
        (zs >= floor_z + OBSTACLE_MIN_HEIGHT)
        & (zs <= floor_z + OBSTACLE_MAX_HEIGHT)
    )

    cols = np.floor(
        (xs - min_x) / RESOLUTION
    ).astype(np.int32)

    rows = np.floor(
        (ys - min_y) / RESOLUTION
    ).astype(np.int32)

    cols = np.clip(
        cols, 0, width - 1
    )

    rows = np.clip(
        rows, 0, height - 1
    )

    floor_counts = np.zeros(
        (height, width),
        dtype=np.int32,
    )

    obstacle_counts = np.zeros(
        (height, width),
        dtype=np.int32,
    )

    np.add.at(
        floor_counts,
        (
            rows[floor_mask],
            cols[floor_mask],
        ),
        1,
    )

    np.add.at(
        obstacle_counts,
        (
            rows[obstacle_mask],
            cols[obstacle_mask],
        ),
        1,
    )

    observed_floor = (
        floor_counts
        >= MIN_FLOOR_POINTS_PER_CELL
    )

    occupied = (
        obstacle_counts
        >= MIN_OBSTACLE_POINTS_PER_CELL
    )

    radius_cells = math.ceil(
        CLEARANCE_RADIUS / RESOLUTION
    )

    kernel_size = (
        2 * radius_cells + 1
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (kernel_size, kernel_size),
    )

    inflated = cv2.dilate(
        occupied.astype(np.uint8),
        kernel,
    ).astype(bool)

    traversable = (
        observed_floor & ~inflated
    )

    def world_to_cell(x, y):
        col = int(
            math.floor(
                (x - min_x) / RESOLUTION
            )
        )

        row = int(
            math.floor(
                (y - min_y) / RESOLUTION
            )
        )

        return row, col

    def cell_to_world(cell):
        row, col = cell

        return [
            min_x
            + (col + 0.5) * RESOLUTION,
            min_y
            + (row + 0.5) * RESOLUTION,
        ]

    return {
        "traversable": traversable,
        "observed_floor": observed_floor,
        "occupied": occupied,
        "inflated": inflated,
        "floor_z": floor_z,
        "resolution": RESOLUTION,
        "origin": [min_x, min_y],
        "width": width,
        "height": height,
        "world_to_cell": world_to_cell,
        "cell_to_world": cell_to_world,
    }


def nearest_traversable(grid, cell):
    height, width = grid.shape
    row, col = cell

    radius = math.ceil(
        MAX_ENDPOINT_DISTANCE / RESOLUTION
    )

    best = None
    best_distance = float("inf")

    for dr in range(
        -radius, radius + 1
    ):
        for dc in range(
            -radius, radius + 1
        ):
            rr = row + dr
            cc = col + dc

            if not (
                0 <= rr < height
                and 0 <= cc < width
            ):
                continue

            if not grid[rr, cc]:
                continue

            distance = math.hypot(
                dr, dc
            )

            if (
                distance * RESOLUTION
                <= MAX_ENDPOINT_DISTANCE
                and distance < best_distance
            ):
                best = (rr, cc)
                best_distance = distance

    return best


def astar(grid, start, goal):
    height, width = grid.shape

    if start == goal:
        return [start]

    neighbors = [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, math.sqrt(2)),
        (-1, 1, math.sqrt(2)),
        (1, -1, math.sqrt(2)),
        (1, 1, math.sqrt(2)),
    ]

    def heuristic(cell):
        return math.hypot(
            cell[0] - goal[0],
            cell[1] - goal[1],
        )

    queue = [
        (heuristic(start), 0.0, start)
    ]

    costs = {
        start: 0.0
    }

    previous = {}
    expanded = 0

    while queue:
        _, current_cost, current = (
            heapq.heappop(queue)
        )

        if current_cost > (
            costs.get(
                current,
                float("inf"),
            ) + 1e-9
        ):
            continue

        if current == goal:
            path = [current]

            while current in previous:
                current = previous[current]
                path.append(current)

            path.reverse()
            return path

        expanded += 1

        if expanded > MAX_ROUTE_NODES:
            return None

        for dr, dc, step_cost in neighbors:
            nr = current[0] + dr
            nc = current[1] + dc

            if not (
                0 <= nr < height
                and 0 <= nc < width
            ):
                continue

            if not grid[nr, nc]:
                continue

            if dr != 0 and dc != 0:
                if not (
                    grid[
                        current[0] + dr,
                        current[1],
                    ]
                    and grid[
                        current[0],
                        current[1] + dc,
                    ]
                ):
                    continue

            neighbor = (nr, nc)
            new_cost = (
                current_cost + step_cost
            )

            if new_cost < costs.get(
                neighbor,
                float("inf"),
            ):
                costs[neighbor] = new_cost
                previous[neighbor] = current

                heapq.heappush(
                    queue,
                    (
                        new_cost
                        + heuristic(neighbor),
                        new_cost,
                        neighbor,
                    ),
                )

    return None


def calculate_plan(
    goal_x,
    goal_y,
    requested_frame,
):
    with _lock:
        pose = (
            dict(_latest_pose)
            if _latest_pose is not None
            else None
        )

        pose_received = _pose_received
        map_received = _map_received
        map_data = _latest_map
        xyz = _latest_xyz

    if (
        pose is None
        or xyz is None
        or map_data is None
    ):
        return {
            "success": False,
            "reason": (
                "Map or localization unavailable"
            ),
        }

    if (
        pose_received is None
        or age_seconds(pose_received)
        > POSE_TIMEOUT
    ):
        return {
            "success": False,
            "reason": "Localization is stale",
        }

    map_frame = map_data["frame_id"]

    if not map_frame or (
        pose["frame_id"] != map_frame
        or requested_frame != map_frame
    ):
        return {
            "success": False,
            "reason": "Coordinate frame mismatch",
            "map_frame": map_frame,
            "pose_frame": pose["frame_id"],
            "requested_frame": requested_frame,
        }

    start = (
        pose["position"]["x"],
        pose["position"]["y"],
    )

    goal = (
        goal_x,
        goal_y,
    )

    try:
        occupancy = build_occupancy(
            xyz,
            start,
            goal,
        )

    except ValueError as error:
        return {
            "success": False,
            "reason": str(error),
        }

    grid = occupancy["traversable"]
    to_cell = occupancy["world_to_cell"]

    start_cell = nearest_traversable(
        grid,
        to_cell(*start),
    )

    goal_cell = nearest_traversable(
        grid,
        to_cell(*goal),
    )

    diagnostics = {
        "floor_z_estimate": (
            occupancy["floor_z"]
        ),
        "floor_method": (
            "legacy_10th_percentile"
        ),
        "resolution_m": RESOLUTION,
        "clearance_radius_m": (
            CLEARANCE_RADIUS
        ),
        "observed_floor_cells": int(
            occupancy["observed_floor"].sum()
        ),
        "occupied_cells": int(
            occupancy["occupied"].sum()
        ),
        "traversable_cells": int(
            grid.sum()
        ),
        "total_cells": int(
            grid.size
        ),
        "map_age_seconds": age_seconds(
            map_received
        ),
    }

    if start_cell is None:
        return {
            "success": False,
            "reason": (
                "No observed traversable floor near "
                "the robot. Floor calibration or "
                "map coverage may be insufficient."
            ),
            "diagnostics": diagnostics,
        }

    if goal_cell is None:
        return {
            "success": False,
            "reason": (
                "No observed traversable floor near "
                "the destination. Verify its location "
                "and extend or calibrate the map."
            ),
            "diagnostics": diagnostics,
        }

    cells = astar(
        grid,
        start_cell,
        goal_cell,
    )

    if cells is None:
        return {
            "success": False,
            "reason": (
                "No connected path through observed "
                "floor cells. Unknown areas remain blocked."
            ),
            "diagnostics": diagnostics,
        }

    path = [
        occupancy["cell_to_world"](cell)
        for cell in cells
    ]

    length = sum(
        math.hypot(
            b[0] - a[0],
            b[1] - a[1],
        )
        for a, b in zip(
            path,
            path[1:],
        )
    )

    return {
        "success": True,
        "mode": "experimental_preview_only",
        "frame_id": map_frame,
        "start": list(start),
        "goal": list(goal),
        "path": path,
        "distance_m": length,
        "waypoint_count": len(path),
        "diagnostics": diagnostics,
        "warnings": [
            "Floor segmentation is not calibrated.",
            "Point-cloud coverage does not prove free space.",
            "Route is not approved for robot execution.",
            "No dynamic obstacle detection is included.",
        ],
        "physical_motion_enabled": False,
    }


def get_floor_diagnostics():
    global _floor_cache
    global _floor_cache_version

    with _floor_compute_lock:
        with _lock:
            points = _latest_xyz
            pose = _latest_pose
            map_data = _latest_map
            map_received = _map_received
            version = _map_version

            cached = _floor_cache
            cached_version = _floor_cache_version

        if (
            points is None
            or pose is None
            or map_data is None
        ):
            return {
                "success": False,
                "reason": (
                    "Waiting for MOLA map and pose"
                ),
                "candidates": [],
                "approved_for_navigation": False,
            }

        # Cache plane extraction for an unchanged map.
        # Robot-relative measurements are refreshed below.
        if (
            cached is None
            or cached_version != version
        ):
            robot_position = pose["position"]

            result = detect_floor_candidates(
                points,
                robot_position,
            )

            with _lock:
                if _map_version == version:
                    _floor_cache = result
                    _floor_cache_version = version

        else:
            result = cached

        # Return a separate payload so cached data is
        # not mutated by individual HTTP requests.
        payload = json.loads(
            json.dumps(result)
        )

        payload["frame_id"] = (
            map_data["frame_id"]
        )

        payload["map_age_seconds"] = (
            age_seconds(map_received)
        )

        payload["map_version"] = version

        payload["robot_position"] = (
            dict(pose["position"])
        )

        robot_x = pose["position"]["x"]
        robot_y = pose["position"]["y"]
        robot_z = pose["position"]["z"]

        for candidate in payload.get(
            "candidates", []
        ):
            normal = candidate["normal"]
            offset = candidate["plane_offset"]

            plane_z = plane_z_at(
                normal,
                offset,
                robot_x,
                robot_y,
            )

            candidate["z_at_robot_xy"] = plane_z

            candidate["robot_z_minus_plane_z"] = (
                robot_z - plane_z
                if plane_z is not None
                else None
            )

            # Support counts reflect the map and
            # robot location at detection time.
            candidate["near_robot_support_note"] = (
                "Computed at diagnostic extraction time"
            )

        payload["approved_for_navigation"] = False

        return payload


# ------------------------------------------------------------
# Experimental occupancy visualization (read-only)
# ------------------------------------------------------------
# This grid deliberately does not declare any cells safe/free.
# A horizontal surface is not necessarily the laboratory floor.
OCCUPANCY_RESOLUTION = 0.20
OCCUPANCY_MAX_CELLS = 200000
OCCUPANCY_MAX_MAP_AGE_SECONDS = 30.0


def get_occupancy_grid():
    with _lock:
        xyz = _latest_xyz
        map_data = _latest_map
        map_received = _map_received
        version = _map_version

    if xyz is None or map_data is None or len(xyz) == 0:
        return {
            "success": False,
            "reason": "Waiting for MOLA point cloud",
            "approved_for_navigation": False,
        }

    age = age_seconds(map_received)
    fresh = age is not None and age <= OCCUPANCY_MAX_MAP_AGE_SECONDS
    points = np.asarray(xyz, dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        return {
            "success": False,
            "reason": "No finite map points",
            "approved_for_navigation": False,
        }

    # All points are initially unknown. Without a verified floor,
    # positive occupancy/free-space labels would be misleading.
    min_xy = np.floor(points[:, :2].min(axis=0) / OCCUPANCY_RESOLUTION) * OCCUPANCY_RESOLUTION
    max_xy = np.ceil(points[:, :2].max(axis=0) / OCCUPANCY_RESOLUTION) * OCCUPANCY_RESOLUTION
    width = int(round((max_xy[0] - min_xy[0]) / OCCUPANCY_RESOLUTION)) + 1
    height = int(round((max_xy[1] - min_xy[1]) / OCCUPANCY_RESOLUTION)) + 1
    if width * height > OCCUPANCY_MAX_CELLS:
        return {
            "success": False,
            "reason": "Map too large for diagnostic occupancy grid",
            "width": width,
            "height": height,
            "approved_for_navigation": False,
        }

    col = np.floor((points[:, 0] - min_xy[0]) / OCCUPANCY_RESOLUTION).astype(np.int32)
    row = np.floor((points[:, 1] - min_xy[1]) / OCCUPANCY_RESOLUTION).astype(np.int32)
    col = np.clip(col, 0, width - 1)
    row = np.clip(row, 0, height - 1)
    point_counts = np.zeros((height, width), dtype=np.int32)
    np.add.at(point_counts, (row, col), 1)

    # 'observed_geometry' means returns were recorded here;
    # it does NOT mean occupied by an obstacle or walkable floor.
    observed = np.argwhere(point_counts > 0)
    cells = [[int(r), int(c), int(point_counts[r, c])] for r, c in observed]
    return {
        "success": True,
        "mode": "diagnostic_only",
        "frame_id": map_data.get("frame_id"),
        "map_version": version,
        "map_age_seconds": age,
        "map_fresh": fresh,
        "maximum_map_age_seconds": OCCUPANCY_MAX_MAP_AGE_SECONDS,
        "resolution_m": OCCUPANCY_RESOLUTION,
        "origin": [float(min_xy[0]), float(min_xy[1])],
        "width": width,
        "height": height,
        "cell_encoding": "[row, column, point_count]",
        "observed_geometry_cells": cells,
        "observed_geometry_count": len(cells),
        "unknown_count": int(width * height - len(cells)),
        "observed_free_count": 0,
        "occupied_count": 0,
        "floor_candidate_count": 0,
        "obstacle_candidate_count": 0,
        "classification": "unclassified_observed_geometry",
        "floor_verified": False,
        "approved_for_navigation": False,
        "physical_motion_enabled": False,
        "warnings": [
            "Observed point-cloud returns are not proof of obstacles or walkable floor.",
            "All cells remain unverified until floor calibration and free-space inference.",
            "Do not execute robot motion using this diagnostic grid.",
        ] + ([] if fresh else ["MOLA map snapshot is stale."]),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(
            self.path
        )

        path = parsed.path

        try:
            if path in ("/", "/status"):
                self.handle_status()

            elif path == "/pose":
                self.handle_pose()

            elif path == "/map":
                self.handle_map()

            elif path == "/plan":
                self.handle_plan(
                    parsed.query
                )

            elif path == "/floor-diagnostics":
                self.handle_floor_diagnostics()

            elif path == "/occupancy-grid":
                self.handle_occupancy_grid()

            else:
                self.send_json(
                    404,
                    {
                        "error": (
                            "Endpoint not found"
                        )
                    },
                )

        except Exception as error:
            self.send_json(
                500,
                {
                    "success": False,
                    "error": str(error),
                },
            )

    def handle_status(self):
        with _lock:
            pose_received = _pose_received
            map_received = _map_received
            has_map = _latest_map is not None

        pose_age = age_seconds(
            pose_received
        )

        map_age = age_seconds(
            map_received
        )

        self.send_json(
            200,
            {
                "service": (
                    "G1 Studio MOLA Map Bridge"
                ),
                "pose_connected": (
                    pose_age is not None
                    and pose_age < POSE_TIMEOUT
                ),
                "map_available": has_map,
                "map_age_seconds": map_age,
                "map_source": MAP_TOPIC,
                "pose_source": POSE_TOPIC,
                "read_only": True,
                "experimental_planner": True,
                "floor_diagnostics_available": True,
                "occupancy_grid_available": True,
                "physical_motion_enabled": False,
            },
        )

    def handle_pose(self):
        with _lock:
            pose = (
                dict(_latest_pose)
                if _latest_pose is not None
                else None
            )
            received = _pose_received

        age = age_seconds(
            received
        )

        self.send_json(
            200,
            {
                "connected": (
                    age is not None
                    and age < POSE_TIMEOUT
                ),
                "source": POSE_TOPIC,
                "age_seconds": age,
                "pose": pose,
            },
        )

    def handle_map(self):
        with _lock:
            payload = _latest_map
            received = _map_received

        if payload is None:
            self.send_json(
                200,
                {
                    "connected": False,
                    "source": MAP_TOPIC,
                    "frame_id": None,
                    "total_points": 0,
                    "displayed_points": 0,
                    "age_seconds": None,
                    "points": [],
                    "message": (
                        "Waiting for MOLA map data"
                    ),
                },
            )
            return

        self.send_json(
            200,
            {
                **payload,
                "age_seconds": age_seconds(
                    received
                ),
            },
        )

    def handle_plan(self, query):
        try:
            params = parse_qs(
                query,
                keep_blank_values=True,
            )

            x = float(
                params["x"][0]
            )

            y = float(
                params["y"][0]
            )

            frame = params[
                "frame_id"
            ][0]

            if not (
                finite_number(x)
                and finite_number(y)
                and frame
            ):
                raise ValueError(
                    "Invalid goal parameters"
                )

        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            self.send_json(
                400,
                {
                    "success": False,
                    "reason": (
                        "Required parameters: "
                        "x, y, frame_id"
                    ),
                },
            )
            return

        result = calculate_plan(
            x,
            y,
            frame,
        )

        self.send_json(
            200,
            result,
        )

    def handle_occupancy_grid(self):
        self.send_json(200, get_occupancy_grid())

    def handle_floor_diagnostics(self):
        result = get_floor_diagnostics()

        self.send_json(
            200,
            result,
        )

    def send_json(self, status, payload):
        body = json.dumps(
            payload,
            allow_nan=False,
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()

        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main():
    rclpy.init()

    node = G1MapBridge()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    server.daemon_threads = True

    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    server_thread.start()

    node.get_logger().info(
        f"G1 MOLA map bridge listening on {PORT}"
    )

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        server.shutdown()
        server.server_close()

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()