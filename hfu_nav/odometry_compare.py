#!/usr/bin/env python3
"""
Compare today's FAST-LIO odometry with the odometry recorded on mapping day.

During a bag replay:
  /Odometry           live FAST-LIO (today's run on the replayed sensor data)
  /recorded/Odometry  the bag's original /Odometry (remapped on playback)

Both start at the same place in the same frame (camera_init), so if FAST-LIO
runs like on mapping day the two paths overlap. Writes into --out:
  odometry_compare.csv, odometry_compare.json, odometry_compare.png
  (png: recorded path blue, live path orange, on the 2D map)

Read-only: publishes nothing. Stop with Ctrl+C.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import signal
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from localization_monitor import read_pgm  # noqa: E402
from pcd_to_nav2_map import write_png  # noqa: E402

MATCH_TOL = 0.06   # s


class Compare:
    def __init__(self):
        self.live: list[tuple[float, float, float, float]] = []
        self.rec: list[tuple[float, float, float, float]] = []

    def add_live(self, t, x, y, z):
        self.live.append((t, x, y, z))

    def add_recorded(self, t, x, y, z):
        self.rec.append((t, x, y, z))

    def pairs(self):
        rec = sorted(self.rec)
        times = [r[0] for r in rec]
        out = []
        for (t, x, y, z) in self.live:
            i = bisect.bisect_left(times, t)
            best = None
            for j in (i - 1, i):
                if 0 <= j < len(rec) and abs(rec[j][0] - t) <= MATCH_TOL:
                    if best is None or abs(rec[j][0] - t) < abs(best[0] - t):
                        best = rec[j]
            if best is not None:
                out.append((t, (x, y, z), best[1:]))
        return out

    def summary(self) -> dict:
        pairs = self.pairs()
        if not pairs:
            return {"verdict": "NO DATA", "live_msgs": len(self.live), "recorded_msgs": len(self.rec)}
        dist = 0.0
        rows = []
        prev = None
        for t, live, rec in pairs:
            if prev is not None:
                dist += math.dist(rec[:2], prev[:2])
            prev = rec
            dxy = math.hypot(live[0] - rec[0], live[1] - rec[1])
            dz = abs(live[2] - rec[2])
            rows.append((dist, dxy, dz))
        arr = np.array(rows)
        at = {}
        for mark in (5, 10, 15, 20, 30, 50, 100, 200, 300):
            k = np.searchsorted(arr[:, 0], mark)
            if k < len(arr):
                at[f"{mark}m"] = {"xy": round(float(arr[k, 1]), 3), "z": round(float(arr[k, 2]), 3)}
        first_bad = next((r[0] for r in rows if r[1] > 0.5 or r[2] > 0.3), None)
        max_xy = float(arr[:, 1].max())
        verdict = ("SAME AS MAPPING DAY" if max_xy < 0.3 else
                   "SMALL DIFFERENCE" if max_xy < 1.0 else
                   "FAST-LIO DIVERGES FROM MAPPING DAY")
        return {
            "verdict": verdict,
            "compared_samples": len(pairs),
            "route_length_m": round(dist, 1),
            "difference_xy_max_m": round(max_xy, 3),
            "difference_z_max_m": round(float(arr[:, 2].max()), 3),
            "difference_final_xy_m": round(float(arr[-1, 1]), 3),
            "difference_at_distance": at,
            "first_diverges_at_m": round(first_bad, 1) if first_bad is not None else None,
            "live_msgs": len(self.live),
            "recorded_msgs": len(self.rec),
        }

    def write(self, out: str, map_dir: str | None) -> dict:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "odometry_compare.csv"), "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["t", "live_x", "live_y", "live_z", "rec_x", "rec_y", "rec_z"])
            for t, live, rec in self.pairs():
                wr.writerow([f"{t:.3f}", *(f"{v:.3f}" for v in live), *(f"{v:.3f}" for v in rec)])
        s = self.summary()
        with open(os.path.join(out, "odometry_compare.json"), "w") as f:
            json.dump(s, f, indent=2)
        if map_dir and self.live and self.rec:
            self.render(map_dir, os.path.join(out, "odometry_compare.png"))
        return s

    def render(self, map_dir: str, out_png: str) -> None:
        img = read_pgm(os.path.join(map_dir, "map.pgm"))
        with open(os.path.join(map_dir, "map_info.json")) as f:
            info = json.load(f)
        R = np.array(info["leveling_rotation"])
        t = np.array(info["leveling_translation"])
        res = info["resolution"]
        ox, oy = info["origin"][0], info["origin"][1]
        rgb = np.empty(img.shape + (3,), dtype=np.uint8)
        rgb[img == 205] = (225, 230, 227)
        rgb[img == 254] = (255, 255, 255)
        rgb[img == 0] = (150, 190, 165)
        h, w = img.shape

        def draw(track, color):
            for (_, x, y, z) in track:
                p = R @ np.array([x, y, z]) + t
                col = int((p[0] - ox) / res)
                row = h - 1 - int((p[1] - oy) / res)
                if 0 <= row < h and 0 <= col < w:
                    rgb[max(0, row - 1):row + 2, max(0, col - 1):col + 2] = color

        draw(self.rec, (30, 90, 220))     # mapping day: blue
        draw(self.live, (240, 140, 20))   # today: orange
        scale = max(1, min(6, 1400 // max(rgb.shape[:2])))
        write_png(out_png, rgb.repeat(scale, axis=0).repeat(scale, axis=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map-dir", default="/ros2_ws/maps/hfu_lab_full/nav2d_session03")
    args, ros_args = ap.parse_known_args()

    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data

    rclpy.init(args=ros_args)
    node = rclpy.create_node("odometry_compare")
    cmp_ = Compare()

    def stamp(msg):
        return msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

    def live(msg):
        p = msg.pose.pose.position
        cmp_.add_live(stamp(msg), p.x, p.y, p.z)

    def rec(msg):
        p = msg.pose.pose.position
        cmp_.add_recorded(stamp(msg), p.x, p.y, p.z)

    node.create_subscription(Odometry, "/Odometry", live, qos_profile_sensor_data)
    node.create_subscription(Odometry, "/recorded/Odometry", rec, qos_profile_sensor_data)

    stop = [False]
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__(0, True))
    last = time.monotonic()
    while not stop[0] and rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0.2)
        if time.monotonic() - last > 15:
            last = time.monotonic()
            s = cmp_.summary()
            print(f"[odom-compare] route {s.get('route_length_m')} m, max xy diff "
                  f"{s.get('difference_xy_max_m')} m, now {s.get('difference_final_xy_m')} m",
                  flush=True)
    s = cmp_.write(args.out, args.map_dir)
    print("\n========== FAST-LIO: TODAY vs MAPPING DAY ==========")
    for k, v in s.items():
        print(f"  {k}: {v}")
    node.destroy_node()
    rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
