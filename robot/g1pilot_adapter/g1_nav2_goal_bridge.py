#!/usr/bin/env python3
"""Authenticated ROS2 Nav2 goal bridge, fail-closed until hardware safety approval.

No Unitree SDK or velocity commands are used here. The Nav2 action server must
be separately connected to a validated, independently stopping locomotion layer.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node

HOST = "127.0.0.1"
PORT = int(os.getenv("G1_NAV2_BRIDGE_PORT", "8771"))
TOKEN = os.getenv("G1_NAV2_GOAL_BRIDGE_TOKEN", "")
# This gate is intentionally not controlled by an environment variable.
# Replace only after independent physical stopping and watchdog validation.
PHYSICAL_NAVIGATION_SAFETY_APPROVED = False
MAX_GOAL_DURATION_S = 120.0


class NavBridge(Node):
    def __init__(self):
        super().__init__("hfu_g1_nav2_goal_bridge")
        self.client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.lock = threading.Lock()
        self.active_goal = None
        self.cancel_requested = False

    def navigate(self, target, x, y, yaw):
        if not PHYSICAL_NAVIGATION_SAFETY_APPROVED:
            return {"status": "locked", "arrived": False,
                    "detail": "Physical locomotion watchdog and stopping not validated"}, 423
        with self.lock:
            if self.active_goal is not None:
                return {"status": "busy", "arrived": False}, 409
            self.active_goal = "pending"
            self.cancel_requested = False
        try:
            if not self.client.wait_for_server(timeout_sec=2.0):
                return {"status": "unavailable", "arrived": False}, 503
            goal = NavigateToPose.Goal()
            goal.pose = PoseStamped()
            goal.pose.header.frame_id = "map"
            goal.pose.header.stamp = self.get_clock().now().to_msg()
            goal.pose.pose.position.x = x
            goal.pose.pose.position.y = y
            goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
            goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
            future = self.client.send_goal_async(goal)
            deadline = time.monotonic() + 5.0
            while not future.done() and time.monotonic() < deadline:
                time.sleep(0.02)
            if not future.done():
                return {"status": "goal_timeout", "arrived": False}, 504
            handle = future.result()
            if handle is None or not handle.accepted:
                return {"status": "rejected", "arrived": False}, 409
            with self.lock:
                self.active_goal = handle
                should_cancel = self.cancel_requested
            if should_cancel:
                handle.cancel_goal_async()
            result_future = handle.get_result_async()
            deadline = time.monotonic() + MAX_GOAL_DURATION_S
            while not result_future.done() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not result_future.done():
                handle.cancel_goal_async()
                return {"status": "timeout", "arrived": False}, 504
            result = result_future.result()
            success = result.status == GoalStatus.STATUS_SUCCEEDED
            return {"status": "succeeded" if success else "failed",
                    "arrived": success, "target": target}, 200
        finally:
            with self.lock:
                self.active_goal = None
                self.cancel_requested = False

    def cancel(self):
        with self.lock:
            handle = self.active_goal
            self.cancel_requested = True
        if handle is None:
            return {"status": "idle"}
        if handle == "pending":
            return {"status": "cancel_requested"}
        handle.cancel_goal_async()
        return {"status": "cancel_requested"}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            return self.respond(200, {"ready": False,
                "physical_navigation_enabled": PHYSICAL_NAVIGATION_SAFETY_APPROVED,
                "detail": "Safety gate locked"})
        self.respond(404, {"error": "not_found"})

    def do_POST(self):
        if not TOKEN or not secrets.compare_digest(self.headers.get("X-G1-Nav-Token", ""), TOKEN):
            return self.respond(401, {"error": "unauthorized"})
        if self.path not in ("/navigate", "/cancel"):
            return self.respond(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 4096:
                raise ValueError("Invalid request length")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            if self.path == "/cancel":
                return self.respond(200, self.server.bridge.cancel())
            target = data.get("target")
            coords = [data.get(k) for k in ("x", "y", "yaw")]
            if not isinstance(target, str) or not target or len(target) > 128:
                raise ValueError("Invalid destination")
            if not all(type(v) in (int, float) and math.isfinite(v) for v in coords):
                raise ValueError("Invalid coordinates")
            response, code = self.server.bridge.navigate(target, *coords)
            self.respond(code, response)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})


def main():
    if not TOKEN:
        raise SystemExit("Set G1_NAV2_GOAL_BRIDGE_TOKEN before starting")
    rclpy.init()
    bridge = NavBridge()
    executor = rclpy.executors.MultiThreadedExecutor(num_threads=2)
    executor.add_node(bridge)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.bridge = bridge
    try:
        print(f"Nav2 bridge listening on {HOST}:{PORT} (PHYSICAL MOTION LOCKED)")
        server.serve_forever()
    finally:
        server.server_close()
        executor.shutdown()
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
