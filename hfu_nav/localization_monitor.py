#!/usr/bin/env python3
"""
Records FAST_LIO_LOCALIZATION output during a test and scores it.

Listens to:
  /localization/status  (std_msgs/String JSON from global_localization)
  /localization         (nav_msgs/Odometry, map -> body)

Writes into --out (a NEW folder):
  localization_log.csv      one row per status / pose message
  localization_summary.json the score
  localization_route.png    route drawn on the 2D map
                            green = localized (accepted match < 2 s ago)
                            red   = not localized

Stop with Ctrl+C (or --duration). Read-only: publishes nothing.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import signal
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcd_to_nav2_map import write_png  # noqa: E402

GOOD_WINDOW = 2.0   # s: pose counts as localized if an accept came this recently


# ----------------------------------------------------------------------
# Pure logic (unit-tested without ROS)
# ----------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.status_rows: list[dict] = []
        self.poses: list[tuple[float, float, float, float, bool]] = []  # t,x,y,z,good
        self.last_accept: float | None = None

    def on_status(self, t: float, data: dict) -> None:
        row = {"t": t, "state": data.get("state", "?"),
               "fitness": data.get("fitness"), "rmse": data.get("rmse"),
               "reason": data.get("reason", "")}
        self.status_rows.append(row)
        if row["state"] == "accepted":
            self.last_accept = t

    def on_pose(self, t: float, x: float, y: float, z: float) -> None:
        good = self.last_accept is not None and t - self.last_accept <= GOOD_WINDOW
        self.poses.append((t, x, y, z, good))

    def summary(self) -> dict:
        states: dict[str, int] = {}
        for r in self.status_rows:
            states[r["state"]] = states.get(r["state"], 0) + 1
        acc = [r for r in self.status_rows if r["state"] == "accepted"]
        fit = np.array([r["fitness"] for r in acc if r["fitness"] is not None], dtype=float)
        rmse = np.array([r["rmse"] for r in acc if r["rmse"] is not None], dtype=float)
        tried = sum(v for k, v in states.items()
                    if k in ("accepted", "rejected_quality", "rejected_jump"))

        dist_total = dist_good = 0.0
        for a, b in zip(self.poses, self.poses[1:]):
            d = math.hypot(b[1] - a[1], b[2] - a[2])
            dist_total += d
            if a[4] and b[4]:
                dist_good += d

        # Longest time without an accepted match (after the first accept).
        accept_times = [r["t"] for r in acc]
        end = self.poses[-1][0] if self.poses else (accept_times[-1] if accept_times else 0)
        gaps = np.diff(accept_times + [end]) if accept_times else np.array([])
        # Measure from the initial pose ("initializing"); ignore rows stamped
        # before the simulated clock started (t == 0).
        starts = [r["t"] for r in self.status_rows if r["state"] == "initializing" and r["t"] > 1]
        valid = [r["t"] for r in self.status_rows if r["t"] > 1]
        t0 = starts[0] if starts else (valid[0] if valid else None)
        first_accept = accept_times[0] - t0 if accept_times and t0 is not None else None

        def stat(a, f):
            return round(float(f(a)), 4) if len(a) else None

        verdict = "NO DATA"
        if self.poses:
            pct = dist_good / dist_total * 100 if dist_total > 0 else 0.0
            longest = float(gaps.max()) if len(gaps) else float("inf")
            if pct >= 95 and longest <= 5 and (stat(rmse, np.median) or 1) <= 0.15:
                verdict = "PASS"
            elif pct >= 80:
                verdict = "PARTIAL - check red sections"
            else:
                verdict = "FAIL"
        return {
            "verdict": verdict,
            "route_length_m": round(dist_total, 1),
            "route_localized_m": round(dist_good, 1),
            "route_localized_percent": round(dist_good / dist_total * 100, 1) if dist_total else 0.0,
            "time_to_first_match_s": round(first_accept, 1) if first_accept is not None else None,
            "longest_gap_without_match_s": round(float(gaps.max()), 1) if len(gaps) else None,
            "matches_accepted": len(acc),
            "match_attempts": tried,
            "acceptance_percent": round(len(acc) / tried * 100, 1) if tried else 0.0,
            "fitness_median": stat(fit, np.median),
            "fitness_min": stat(fit, np.min),
            "rmse_median_m": stat(rmse, np.median),
            "rmse_p95_m": stat(rmse, lambda a: np.percentile(a, 95)),
            "status_counts": states,
            "pass_rule": ">=95% of route localized, no gap >5 s, median RMSE <=0.15 m",
        }


def read_pgm(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        data = f.read()
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    return np.frombuffer(parts[3][: w * h], dtype=np.uint8).reshape(h, w)


def render_route(map_dir: str, poses, out_png: str, name: str = "map") -> None:
    """Draw route (PCD/localization frame) on the leveled 2D map."""
    img = read_pgm(os.path.join(map_dir, f"{name}.pgm"))
    with open(os.path.join(map_dir, f"{name}_info.json")) as f:
        info = json.load(f)
    R = np.array(info["leveling_rotation"])
    t = np.array(info["leveling_translation"])
    res = info["resolution"]
    ox, oy = info["origin"][0], info["origin"][1]

    rgb = np.empty(img.shape + (3,), dtype=np.uint8)
    rgb[img == 205] = (225, 230, 227)
    rgb[img == 254] = (255, 255, 255)
    rgb[img == 0] = (150, 190, 165)        # muted obstacles so the route stands out
    h, w = img.shape
    for (_, x, y, z, good) in poses:
        p = R @ np.array([x, y, z]) + t
        col = int((p[0] - ox) / res)
        row = h - 1 - int((p[1] - oy) / res)
        color = (8, 123, 57) if good else (220, 30, 30)
        rgb[max(0, row - 1):row + 2, max(0, col - 1):col + 2] = color
    if poses:
        for idx, color in ((0, (30, 90, 220)), (-1, (0, 0, 0))):   # start blue, end black
            _, x, y, z, _ = poses[idx]
            p = R @ np.array([x, y, z]) + t
            col = int((p[0] - ox) / res)
            row = h - 1 - int((p[1] - oy) / res)
            rgb[max(0, row - 4):row + 5, max(0, col - 4):col + 5] = color
    scale = max(1, min(6, 1400 // max(rgb.shape[:2])))
    write_png(out_png, rgb.repeat(scale, axis=0).repeat(scale, axis=1))


def write_outputs(rec: Recorder, out: str, map_dir: str | None) -> dict:
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "localization_log.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t", "kind", "state", "fitness", "rmse", "x", "y", "z", "localized", "reason"])
        for r in rec.status_rows:
            wr.writerow([f"{r['t']:.3f}", "status", r["state"], r["fitness"], r["rmse"], "", "", "", "", r["reason"]])
        for (t, x, y, z, good) in rec.poses:
            wr.writerow([f"{t:.3f}", "pose", "", "", "", f"{x:.3f}", f"{y:.3f}", f"{z:.3f}", int(good), ""])
    summary = rec.summary()
    with open(os.path.join(out, "localization_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    if map_dir and rec.poses:
        render_route(map_dir, rec.poses, os.path.join(out, "localization_route.png"))
    return summary


# ----------------------------------------------------------------------
# ROS node
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map-dir", default="/ros2_ws/maps/hfu_lab_full/nav2d_session03")
    ap.add_argument("--duration", type=float, default=0.0, help="seconds (0 = until Ctrl+C)")
    ap.add_argument("--pose-every", type=float, default=0.2, help="log a pose every N s")
    args, ros_args = ap.parse_known_args()

    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from std_msgs.msg import String

    rclpy.init(args=ros_args)
    node = rclpy.create_node("localization_monitor")
    rec = Recorder()
    last_pose = [0.0]
    clock = node.get_clock()

    def now() -> float:
        return clock.now().nanoseconds / 1e9

    def on_status(msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except ValueError:
            return
        rec.on_status(now(), data)
        if data.get("state") != "accepted":
            node.get_logger().info(f"status: {msg.data[:160]}")

    def on_pose(msg: Odometry) -> None:
        t = now()
        if t - last_pose[0] < args.pose_every:
            return
        last_pose[0] = t
        p = msg.pose.pose.position
        rec.on_pose(t, p.x, p.y, p.z)

    latched = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(String, "/localization/status", on_status, latched)
    node.create_subscription(Odometry, "/localization", on_pose, 10)

    stop = [False]
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__(0, True))
    started = time.monotonic()
    last_print = started
    print("[monitor] recording /localization and /localization/status ... Ctrl+C to finish",
          flush=True)
    while not stop[0] and rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.2)
        if args.duration and time.monotonic() - started > args.duration:
            break
        if time.monotonic() - last_print > 15:
            last_print = time.monotonic()
            s = rec.summary()
            print(f"[monitor] route {s['route_length_m']} m, localized "
                  f"{s['route_localized_percent']}%, accepted {s['matches_accepted']}/"
                  f"{s['match_attempts']}, rmse median {s['rmse_median_m']}", flush=True)

    summary = write_outputs(rec, args.out, args.map_dir)
    print("\n========== LOCALIZATION RESULT ==========")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"Files in {args.out}")
    node.destroy_node()
    rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
