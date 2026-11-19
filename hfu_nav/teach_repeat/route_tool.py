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

  # LAB TOUR: record one walk through the lab and mark the stops.
  # At each exhibit: stop, turn G1 to face it, type a name, press Enter.
  # End the tour back on HOME (then G1 needs no extra way back).
  python3 route_tool.py record lab_tour --title-en "HFU lab tour" \
          --title-de "HFU Laborführung" --tour
  # write what G1 says at each stop
  python3 route_tool.py stops lab_tour
  python3 route_tool.py stop-text lab_tour 1 --title-en "3D printer" \
          --title-de "3D-Drucker" --text-en "This is our 3D printer..." \
          --text-de "Das ist unser 3D-Drucker..."
"""
from __future__ import annotations

import argparse
import math
import os
import queue
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_core import (FollowParams, OdometryWatch, Route, RouteRecorder,  # noqa: E402
                        SafetyError, wrap, yaw_from_quaternion)
from guide_service import ROUTES_DIR, list_routes  # noqa: E402

from home_align import home_scan_path, save_home_scan, slice_2d  # noqa: E402

MARK_FILE = "/tmp/g1_tour_marks.txt"
HOME_SCAN_SECONDS = 3.0


def ros_odometry(callback, topic="/Odometry", cloud_callback=None, cloud_topic="/cloud_registered"):
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data

    rclpy.init()
    node = rclpy.create_node("route_tool")

    def on(msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        callback(time.monotonic(), p.x, p.y, p.z, yaw_from_quaternion(q.x, q.y, q.z, q.w))

    node.create_subscription(Odometry, topic, on, qos_profile_sensor_data)
    if cloud_callback is not None:
        from sensor_msgs.msg import PointCloud2
        from guide_service import cloud_to_xyz
        node.create_subscription(PointCloud2, cloud_topic,
                                 lambda m: cloud_callback(lambda: cloud_to_xyz(m)), qos_profile_sensor_data)
    return rclpy, node


def spin_until_ctrl_c(rclpy, node, tick, every=1.0, poll=None):
    stop = [False]
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    last = 0.0
    while not stop[0] and rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.1)
        if poll is not None:
            poll()
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

    # HOME scan: LiDAR view of the room during the first seconds (G1 standing on HOME).
    home = {"clouds": [], "t0": None, "done": False, "start": None}

    def on_cloud(get_xyz):
        if home["done"] or state["last"] is None:
            return
        xyz = get_xyz()
        if xyz is None:
            return
        _, x, y, _, _ = state["last"]
        if home["start"] is None:
            home["start"] = (x, y)
            home["t0"] = time.monotonic()
        moved = math.hypot(x - home["start"][0], y - home["start"][1])
        if moved > 0.05 or time.monotonic() - home["t0"] > HOME_SCAN_SECONDS:
            home["done"] = True
            print(f"  HOME scan captured ({len(home['clouds'])} scans)"
                  + ("" if home["clouds"] else " - EMPTY, keep G1 still at the start next time"))
            return
        home["clouds"].append(xyz)

    rclpy, node = ros_odometry(on, args.topic, cloud_callback=on_cloud)
    print(f"KEEP G1 STILL for {HOME_SCAN_SECONDS:.0f} s (HOME scan), then drive.")
    print(f"Recording '{args.name}'. Drive G1 with the app joystick to the destination,")
    print("then stop and press Ctrl+C here.")
    lines: queue.Queue = queue.Queue()
    planned = [n.strip().replace(" ", "_") for n in (args.stops or "").split(",") if n.strip()]
    if args.tour:
        try:                                   # fresh mark file for `route_tool.py mark`
            open(MARK_FILE, "w").close()
            os.chmod(MARK_FILE, 0o666)
        except OSError:
            pass
        print("=" * 70)
        print("TOUR: at each exhibit STOP G1 and TURN it to FACE the exhibit, then")
        if planned:
            print(f"      just press ENTER. Planned stops: {', '.join(planned)}")
        else:
            print("      type a short name (e.g. 3d_printer) and press Enter.")
        print("      (or in a 2nd terminal: route_tool.py mark)")
        print("      Finish the tour back on HOME, then Ctrl+C.")
        print("=" * 70)

        def read_stdin():
            for line in sys.stdin:
                lines.put(line.strip())
        threading.Thread(target=read_stdin, daemon=True).start()

    def next_name() -> str:
        k = len(rec.stops)
        return planned[k] if k < len(planned) else ""

    def poll():
        if args.tour:
            try:
                with open(MARK_FILE, "r+") as f:
                    pending = [ln.strip() for ln in f.read().splitlines()]
                    if pending:
                        f.seek(0)
                        f.truncate()
                for ln in pending:
                    lines.put(ln)
            except OSError:
                pass
        while not lines.empty():
            name = lines.get() or next_name()
            try:
                st = rec.mark_stop(name)
                print(f"\n  >>>>> STOP {len(rec.stops)} '{st['name']}' MARKED, facing "
                      f"{math.degrees(st['yaw']):+.0f} deg <<<<<")
                if next_name():
                    print(f"  >>>>> next: {next_name()}")
                elif planned:
                    print("  >>>>> all planned stops done - drive back to HOME, then Ctrl+C")
                print()
            except ValueError as exc:
                print(f"  >> stop NOT marked: {exc}")

    def tick():
        last = state["last"]
        if last is None:
            print("  waiting for /Odometry ... (is FAST-LIO running? ROS_DOMAIN_ID?)")
            return
        length = Route(args.name, rec.points + [[last[1], last[2], last[3]]], 0, 0).length \
            if rec.points else 0.0
        if state["error"]:
            if not state.get("error_shown"):
                state["error_shown"] = True
                print("\n" + "!" * 70)
                print(f"!! FAST-LIO PROBLEM: {state['error']}")
                print("!! This recording will NOT be saved. Press Ctrl+C, drive G1 back to HOME,")
                print("!! run g1_stop_guide.sh + g1_start_guide.sh and try again.")
                print("!" * 70)
            return
        extra = ""
        if args.tour:
            nxt = next_name()
            extra = f" | stops {len(rec.stops)}" + (f" | next: {nxt} (Enter)" if nxt else "")
        print(f"  {length:5.1f} m, heading {math.degrees(last[4]):+.0f} deg{extra}")

    spin_until_ctrl_c(rclpy, node, tick, every=3.0 if args.tour else 1.0, poll=poll)
    if state["error"]:
        print(f"NOT saved: {state['error']}")
        return 1
    try:
        route = rec.finish(title_en=args.title_en or args.name.replace("_", " "),
                           title_de=args.title_de or args.name.replace("_", " "),
                           arrival_en=args.arrival_en or args.intro_en or "",
                           arrival_de=args.arrival_de or args.intro_de or "")
    except ValueError as exc:
        print(f"NOT saved: {exc}")
        return 1
    path = route.save(folder)
    os.chmod(path, 0o666)
    print(f"Saved {path}: {route.length:.1f} m, {len(route.points)} points.")
    if home["clouds"]:
        import numpy as np
        xy = slice_2d(np.concatenate(home["clouds"]), FollowParams().lidar_height)
        save_home_scan(home_scan_path(path), xy)
        print(f"Saved HOME scan ({len(xy)} wall points) - the guide will auto-correct small "
              "placement errors at HOME.")
    else:
        hp = home_scan_path(path)
        if os.path.exists(hp):
            os.remove(hp)                      # old scan would not match this new route
        print("No HOME scan saved - the guide will rely on exact placement on HOME.")
    if route.stops:
        print(f"Tour with {len(route.stops)} stops" + (" (ends on HOME - loop)" if route.is_loop
              else " (does NOT end on HOME - G1 will walk the whole way back)"))
        print(f"Next: python3 route_tool.py stops {route.name}   and   stop-text ... to add explanations.")
    return 0


def _load(args) -> tuple[Route, str]:
    path = os.path.join(os.path.abspath(args.routes), f"{args.name}.json")
    return Route.load(path), path


def cmd_stops(args) -> int:
    route, _ = _load(args)
    if not route.stops:
        print(f"'{route.name}' has no stops (not a tour).")
        return 1
    print(f"{route.name}: {route.length:.1f} m, {len(route.stops)} stops, "
          + ("loop (ends on HOME)" if route.is_loop else "walks back home at the end"))
    for k, st in enumerate(route.stops, start=1):
        print(f"  {k}. {st['name']}  EN '{st.get('title_en', '')}'  DE '{st.get('title_de', '')}'")
        print(f"       EN: {st.get('text_en') or '(default: Here you can see the ...)'}")
        print(f"       DE: {st.get('text_de') or '(default: Hier sehen Sie: ...)'}")
    return 0


def cmd_stop_text(args) -> int:
    route, path = _load(args)
    if not 1 <= args.number <= len(route.stops):
        print(f"Stop number must be 1..{len(route.stops)}")
        return 1
    st = route.stops[args.number - 1]
    for key in ("title_en", "title_de", "text_en", "text_de"):
        val = getattr(args, key)
        if val is not None:
            st[key] = val
    route.save(os.path.dirname(path))
    print(f"Updated stop {args.number} '{st['name']}'.")
    return 0


def cmd_obstacles(args) -> int:
    """Live view of what the guide's obstacle check sees in front of G1."""
    import numpy as np
    from guide_service import RosSensors
    from route_core import Follower, obstacle_mask_on_path
    p = FollowParams()
    if os.environ.get("G1_GUIDE_OBSTACLE_HALF_WIDTH"):
        p.obstacle_half_width = float(os.environ["G1_GUIDE_OBSTACLE_HALF_WIDTH"])
    follower = None
    if args.route:
        follower = Follower(Route.load(os.path.join(os.path.abspath(args.routes), f"{args.route}.json")), p)
    sensors = RosSensors(args.topic, "/cloud_registered")
    print(f"Obstacle box: {p.obstacle_ahead_min}-{p.obstacle_ahead_max} m ahead, "
          f"+-{p.obstacle_half_width} m wide, {p.obstacle_min_height}-{p.obstacle_max_height} m high, "
          f"stop at >= {p.obstacle_min_points} points. Ctrl+C to finish.")
    try:
        while True:
            time.sleep(1.0)
            pose, pts = sensors.pose(), sensors.points()
            if pose is None or pts is None:
                print("  waiting for /Odometry and /cloud_registered ...")
                continue
            _, x, y, z, yaw = pose
            d = np.asarray(pts)[:, :3] - np.array([x, y, z])
            c, sn = math.cos(yaw), math.sin(yaw)
            fwd = d[:, 0] * c + d[:, 1] * sn
            side = -d[:, 0] * sn + d[:, 1] * c
            h = d[:, 2] + p.lidar_height
            m = ((fwd > p.obstacle_ahead_min) & (fwd < p.obstacle_ahead_max)
                 & (np.abs(side) < p.obstacle_half_width)
                 & (h > p.obstacle_min_height) & (h < p.obstacle_max_height))
            n = int(m.sum())
            if follower is not None:
                follower.idx = int(np.argmin(np.hypot(follower.xy[:, 0] - x, follower.xy[:, 1] - y)))
                mk, inf = obstacle_mask_on_path(pts, (x, y, z), yaw, follower.path_ahead(), p)
                n_path = int(mk.sum())
                verdict = "BLOCKED" if n_path >= p.obstacle_min_points else "free"
                det = ""
                if n_path:
                    det = (f" | ahead {inf['fwd'][mk].min():.2f}-{inf['fwd'][mk].max():.2f} m, side "
                           f"{inf['side'][mk].min():+.2f}..{inf['side'][mk].max():+.2f} m, height "
                           f"{inf['height'][mk].min():.2f}-{inf['height'][mk].max():.2f} m, "
                           f"from path {np.min(inf['to_path'][mk]):.2f}-"
                           f"{np.max(np.where(np.isfinite(inf['to_path'][mk]), inf['to_path'][mk], 0)):.2f} m")
                print(f"  GUIDE (path corridor +-{p.obstacle_half_width} m): {verdict:8s} {n_path:4d} points{det}"
                      f"   [G1 {math.hypot(x - follower.xy[follower.idx, 0], y - follower.xy[follower.idx, 1]):.2f} m from route]")
            verdict = "BLOCKED" if n >= p.obstacle_min_points else "free"
            line = f"  straight box: {verdict:8s} {n:4d} points"
            if n:
                line += (f" | ahead {fwd[m].min():.2f}-{fwd[m].max():.2f} m, side "
                         f"{side[m].min():+.2f}..{side[m].max():+.2f} m (+ = left), "
                         f"height {h[m].min():.2f}-{h[m].max():.2f} m")
            print(line)
    except KeyboardInterrupt:
        return 0


def cmd_mark(args) -> int:
    """Mark a tour stop from a second terminal (the recorder picks it up)."""
    if not os.path.exists(MARK_FILE):
        print("No tour recording is running (start: route_tool.py record NAME --tour).")
        return 1
    with open(MARK_FILE, "a") as f:
        f.write((args.stop_name or "") + "\n")
    print("Stop sent - look for 'STOP n MARKED' in the recording terminal.")
    return 0


def cmd_list(args) -> int:
    routes = list_routes(os.path.abspath(args.routes))
    if not routes:
        print("No routes yet.")
    for r in routes:
        kind = f"tour, {len(r['stops'])} stops" if r.get("kind") == "tour" else "route"
        print(f"  {r['name']:20s} {kind:16s} {r['length_m']:6.1f} m   EN '{r['title_en']}'  DE '{r['title_de']}'  ({r['created']})")
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
    r.add_argument("--tour", action="store_true", help="lab tour: mark stops by typing a name + Enter")
    r.add_argument("--stops", help='tour only: planned stop names in order, e.g. '
                   '"yaskawa_robot,3d_printer,coffee_machine" -> just press Enter at each')
    r.add_argument("--intro-en", help="tour only: what G1 says at the start")
    r.add_argument("--intro-de")
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("name")
    sub.add_parser("odom")
    o = sub.add_parser("obstacles", help="live: what does the obstacle check see?")
    o.add_argument("route", nargs="?", help="e.g. lab_tour: also show the guide's path check")
    m = sub.add_parser("mark", help="mark a tour stop from a 2nd terminal")
    m.add_argument("stop_name", nargs="?")
    s = sub.add_parser("stops")
    s.add_argument("name")
    t = sub.add_parser("stop-text")
    t.add_argument("name")
    t.add_argument("number", type=int)
    t.add_argument("--title-en")
    t.add_argument("--title-de")
    t.add_argument("--text-en")
    t.add_argument("--text-de")
    args = ap.parse_args()
    return {"record": cmd_record, "list": cmd_list, "check": cmd_check, "odom": cmd_odom,
            "stops": cmd_stops, "stop-text": cmd_stop_text, "mark": cmd_mark,
            "obstacles": cmd_obstacles}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
