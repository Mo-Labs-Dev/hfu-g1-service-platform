#!/usr/bin/env python3
"""
HFU G1 Studio - Read-only Livox LiDAR HTTP bridge.

ROS input:
    /livox/lidar (sensor_msgs/msg/PointCloud2)

Local HTTP endpoints:
    GET /health
    GET /points

This service never publishes robot commands.
"""

from __future__ import annotations

import json
import math
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, PointField


HOST = "127.0.0.1"
PORT = 8765
TOPIC = "/livox/lidar"
MAX_POINTS = 1200

_lock = threading.Lock()

_state = {
    "connected": False,
    "frame_id": None,
    "received_at": None,
    "total_points": 0,
    "points": [],
}


class LidarBridge(Node):
    def __init__(self):
        super().__init__("hfu_g1_lidar_http_bridge")

        self.subscription = self.create_subscription(
            PointCloud2,
            TOPIC,
            self.on_cloud,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            f"Listening for LiDAR point clouds on {TOPIC}"
        )

    def on_cloud(self, msg: PointCloud2):
        fields = {field.name: field for field in msg.fields}

        if not all(name in fields for name in ("x", "y", "z")):
            self.get_logger().warning(
                "PointCloud2 is missing x, y or z fields"
            )
            return

        coordinates = [fields[name] for name in ("x", "y", "z")]

        if not all(
            field.datatype == PointField.FLOAT32
            for field in coordinates
        ):
            self.get_logger().warning(
                "Expected FLOAT32 x/y/z coordinates"
            )
            return

        endian = ">" if msg.is_bigendian else "<"
        offsets = [field.offset for field in coordinates]

        total = msg.width * msg.height
        stride = max(1, math.ceil(total / MAX_POINTS))

        points = []

        for index in range(0, total, stride):
            row = index // msg.width
            col = index % msg.width

            base = row * msg.row_step + col * msg.point_step

            try:
                x, y, z = (
                    struct.unpack_from(
                        endian + "f",
                        msg.data,
                        base + offset,
                    )[0]
                    for offset in offsets
                )
            except (struct.error, ValueError):
                continue

            if not all(math.isfinite(v) for v in (x, y, z)):
                continue

            points.append([
                round(x, 3),
                round(y, 3),
                round(z, 3),
            ])

        with _lock:
            _state.update({
                "connected": True,
                "frame_id": msg.header.frame_id,
                "received_at": time.time(),
                "total_points": total,
                "points": points,
            })


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/health", "/points"):
            self.send_json({"error": "Not found"}, 404)
            return

        with _lock:
            snapshot = dict(_state)

        age = (
            time.time() - snapshot["received_at"]
            if snapshot["received_at"] is not None
            else None
        )

        snapshot["connected"] = (
            age is not None and age < 3.0
        )
        snapshot["age_seconds"] = (
            round(age, 2) if age is not None else None
        )

        if self.path == "/health":
            snapshot.pop("points", None)
        elif not snapshot["connected"]:
            snapshot["points"] = []

        self.send_json(snapshot)

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Access-Control-Allow-Origin",
            "http://localhost:3000",
        )
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format_string, *args):
        return


def main():
    rclpy.init()
    node = LidarBridge()

    server = ThreadingHTTPServer(
        (HOST, PORT),
        RequestHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    print(
        f"G1 LiDAR HTTP bridge listening at "
        f"http://{HOST}:{PORT}",
        flush=True,
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()