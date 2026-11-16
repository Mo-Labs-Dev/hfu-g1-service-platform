#!/usr/bin/env python3
"""
Teach routes and check the robot position. Run INSIDE g1pilot-dev with live
FAST-LIO running (FAST-LIO must be started with G1 on the home spot).

  # 1. record: then drive with the app joystick, Ctrl+C at the destination
  python3 route_tool.py record coffee_machine --title-en "coffee machine" \
          --title-de "Kaffeemaschine"
  # list taught routes
  python3 route_tool.py list
  # am I on the home spot? (before guiding)
  python3 route_tool.py check coffee_machine
  # live odometry check: walk 5 m forward, it should show ~5 m
  python3 route_tool.py odom
"""
from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_core import (FollowParams, OdometryWatch, Route, RouteRecorder,  # noqa: E402
                        SafetyError, wrap, yaw_from_quaternion)
from guide_service import ROUTES_DIR, list_routes  # noqa: E402


def ros_odometry(callback, topic="/Odometry"):
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data

    rclpy.init()
    node = rclpy.create_node("route_tool")

    def on(msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        callback(time.monotonic(), p.x, p.y, p.z, yaw_from_quaternion(q.x, q.y, q.z, q.w))

    node.create_subscription(Odometry, topic, on, qos_profile_sensor_data)
    return rclpy, node


def spin_until_ctrl_c(rclpy, node, tick, every=1.0):
    stop = [False]
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    last = 0.0
    while not stop[0] and rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.1)
        if time.monotonic() - last > every:
            last = time.monotonic()
            tick()
    node.destroy_node()
    rclpy.try_shutdown()


def cmd_record(args) -> int:
    folder = os.path.abspath(args.routes)
    if os.path.exists(os.path.join(folder, f"{args.name}.json")) and not args.overwrite:
        print(f"Route '{args.name}' exists. Use --overwrite to replace it.")
        return 2
    rec = RouteRecorder(args.name)
    watch = OdometryWatch(FollowParams())
    state = {"last": None, "error": None}

    def on(t, x, y, z, yaw):
        state["last"] = (t, x, y, z, yaw)
        try:
            watch.update(t, x, y, z)
        except SafetyError as exc:
            state["error"] = str(exc)
        rec.add(x, y, z, yaw)

    rclpy, node = ros_odometry(on, args.topic)
    print(f"Recording '{args.name}'. Drive G1 with the app joystick to the destination,")
    print("then stop and press Ctrl+C here.")

    def tick():
        last = state["last"]
        if last is None:
            print("  waiting for /Odometry ... (is FAST-LIO running? ROS_DOMAIN_ID?)")
            return
        length = Route(args.name, rec.points + [[last[1], last[2], last[3]]], 0, 0).length \
            if rec.points else 0.0
        print(f"  {len(rec.points):4d} points, {length:5.1f} m, pos ({last[1]:+.2f}, {last[2]:+.2f}), "
              f"heading {math.degrees(last[4]):+.0f} deg" + ("   !! " + state["error"] if state["error"] else ""))

    spin_until_ctrl_c(rclpy, node, tick)
    if state["error"]:
        print(f"NOT saved: {state['error']}")
        return 1
    try:
        route = rec.finish(title_en=args.title_en or args.name.replace("_", " "),
                           title_de=args.title_de or args.name.replace("_", " "),
                           arrival_en=args.arrival_en or "", arrival_de=args.arrival_de or "")
    except ValueError as exc:
        print(f"NOT saved: {exc}")
        return 1
    path = route.save(folder)
    os.chmod(path, 0o666)
    print(f"Saved {path}: {route.length:.1f} m, {len(route.points)} points.")
    return 0


def cmd_list(args) -> int:
    routes = list_routes(os.path.abspath(args.routes))
    if not routes:
        print("No routes yet.")
    for r in routes:
        print(f"  {r['name']:20s} {r['length_m']:6.1f} m   EN '{r['title_en']}'  DE '{r['title_de']}'  ({r['created']})")
    return 0


def cmd_check(args) -> int:
    route = Route.load(os.path.join(os.path.abspath(args.routes), f"{args.name}.json"))
    state = {"last": None}
    rclpy, node = ros_odometry(lambda *a: state.__setitem__("last", a), args.topic)

    def tick():
        if state["last"] is None:
            print("  waiting for /Odometry ...")
            return
        _, x, y, _, yaw = state["last"]
        d = math.hypot(x - route.points[0][0], y - route.points[0][1])
        dyaw = math.degrees(wrap(yaw - route.start_yaw))
        ok = d < FollowParams().start_max_dist and abs(dyaw) < FollowParams().start_max_yaw_deg
        print(f"  distance to route start {d:.2f} m, heading off {dyaw:+.0f} deg  ->  "
              + ("OK, ready to guide" if ok else "NOT at the home spot"))

    print("Ctrl+C to finish.")
    spin_until_ctrl_c(rclpy, node, tick)
    return 0


def cmd_odom(args) -> int:
    state = {"first": None, "last": None, "dist": 0.0, "prev": None}

    def on(t, x, y, z, yaw):
        if state["first"] is None:
            state["first"] = (x, y, z)
        if state["prev"] is not None:
            state["dist"] += math.hypot(x - state["prev"][0], y - state["prev"][1])
        state["prev"] = (x, y)
        state["last"] = (x, y, z, yaw)

    rclpy, node = ros_odometry(on, args.topic)
    print("Live FAST-LIO check. Walk G1 ~5 m straight forward with the joystick. Ctrl+C to finish.")

    def tick():
        if state["last"] is None:
            print("  waiting for /Odometry ... (is FAST-LIO running? ROS_DOMAIN_ID?)")
            return
        x, y, z, yaw = state["last"]
        fx, fy, fz = state["first"]
        print(f"  straight-line {math.hypot(x - fx, y - fy):5.2f} m | walked {state['dist']:5.2f} m | "
              f"height change {z - fz:+.2f} m | heading {math.degrees(yaw):+.0f} deg")

    spin_until_ctrl_c(rclpy, node, tick)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--routes", default=ROUTES_DIR)
    ap.add_argument("--topic", default="/Odometry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("name")
    r.add_argument("--title-en")
    r.add_argument("--title-de")
    r.add_argument("--arrival-en", help='e.g. "Here is the coffee machine. Enjoy!"')
    r.add_argument("--arrival-de")
    r.add_argument("--overwrite", action="store_true")
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("name")
    sub.add_parser("odom")
    args = ap.parse_args()
    return {"record": cmd_record, "list": cmd_list, "check": cmd_check, "odom": cmd_odom}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
