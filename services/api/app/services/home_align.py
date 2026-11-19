"""
Automatic HOME alignment (no ROS - unit tested).

Teach & repeat stores routes in the FAST-LIO frame of the teaching run, whose
origin is wherever G1 stood when FAST-LIO started. If G1 is placed a little
differently before guiding (a few cm / degrees), the whole route is shifted /
rotated - on a 70 m tour that is metres at the far end.

Fix: while recording, save a 2D LiDAR "photo" of the room at HOME. Before
guiding, take a new photo and match the two (2D ICP). The result is the small
transform between today's frame and the teaching frame; poses and scan points
are converted with it, so G1 follows the route where it really was taught.
"""
from __future__ import annotations

import math
import os

import numpy as np

SLICE_MIN_H = 0.30      # m above floor - ignores floor and low clutter
SLICE_MAX_H = 2.20      # m above floor - ignores ceiling
MAX_RANGE = 15.0        # m from HOME
VOXEL = 0.05            # m


def home_scan_path(route_json_path: str) -> str:
    return route_json_path[:-5] + ".home.npz" if route_json_path.endswith(".json") \
        else route_json_path + ".home.npz"


def slice_2d(points: np.ndarray, lidar_height: float, origin_xy=(0.0, 0.0)) -> np.ndarray:
    """Wall points (x, y) at 0.3-2.2 m above the floor, voxel-downsampled."""
    if points is None or len(points) == 0:
        return np.zeros((0, 2))
    p = np.asarray(points, dtype=float)[:, :3]
    h = p[:, 2] + lidar_height
    xy = p[(h > SLICE_MIN_H) & (h < SLICE_MAX_H)][:, :2]
    xy = xy[np.hypot(xy[:, 0] - origin_xy[0], xy[:, 1] - origin_xy[1]) < MAX_RANGE]
    if len(xy) == 0:
        return xy
    keys = np.floor(xy / VOXEL).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    return xy[np.sort(idx)]


def _nearest(src: np.ndarray, dst: np.ndarray, grid: dict, cell: float):
    """Nearest dst point for every src point using a coarse hash grid (no scipy)."""
    out_d = np.full(len(src), np.inf)
    out_i = np.zeros(len(src), dtype=np.int64)
    keys = np.floor(src / cell).astype(np.int64)
    for k in range(len(src)):
        kx, ky = keys[k]
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                c = grid.get((kx + dx, ky + dy))
                if c is not None:
                    cand.append(c)
        if not cand:
            continue
        ids = np.concatenate(cand)
        d = np.hypot(dst[ids, 0] - src[k, 0], dst[ids, 1] - src[k, 1])
        j = int(np.argmin(d))
        out_d[k], out_i[k] = d[j], ids[j]
    return out_d, out_i


def _grid(dst: np.ndarray, cell: float) -> dict:
    keys = np.floor(dst / cell).astype(np.int64)
    grid: dict = {}
    for i, (kx, ky) in enumerate(keys):
        grid.setdefault((int(kx), int(ky)), []).append(i)
    return {k: np.asarray(v) for k, v in grid.items()}


def apply(T, xy: np.ndarray) -> np.ndarray:
    tx, ty, th = T
    c, s = math.cos(th), math.sin(th)
    xy = np.asarray(xy, dtype=float)
    return np.stack([c * xy[:, 0] - s * xy[:, 1] + tx, s * xy[:, 0] + c * xy[:, 1] + ty], axis=1)


def icp_2d(src: np.ndarray, dst: np.ndarray, init=(0.0, 0.0, 0.0), iters: int = 40,
           max_points: int = 2500, seed: int = 0):
    """Find T = (tx, ty, theta) so that apply(T, src) lies on dst.
    Returns T, fitness (share of src within 10 cm) and rmse of those."""
    rng = np.random.default_rng(seed)
    if len(src) > max_points:
        src = src[rng.choice(len(src), max_points, replace=False)]
    cell = 0.5
    grid = _grid(dst, cell)
    T = np.array(init, dtype=float)
    for it in range(iters):
        reject = max(0.15, 0.6 * (1 - it / iters))        # coarse -> fine
        moved = apply(T, src)
        d, j = _nearest(moved, dst, grid, cell)
        ok = d < reject
        if ok.sum() < 30:
            break
        a, b = moved[ok], dst[j[ok]]
        ca, cb = a.mean(axis=0), b.mean(axis=0)
        H = (a - ca).T @ (b - cb)
        dth = math.atan2(H[0, 1] - H[1, 0], H[0, 0] + H[1, 1])
        c, s = math.cos(dth), math.sin(dth)
        R = np.array([[c, -s], [s, c]])
        t = cb - R @ ca
        # compose: new = R * (old_T(src)) + t
        tx, ty, th = T
        new_xy = R @ np.array([tx, ty]) + t
        T = np.array([new_xy[0], new_xy[1], th + dth])
        if abs(dth) < 1e-5 and np.hypot(*t) < 1e-4:
            break
    d, _ = _nearest(apply(T, src), dst, grid, cell)
    good = d < 0.10
    fitness = float(good.mean()) if len(d) else 0.0
    rmse = float(np.sqrt(np.mean(d[good] ** 2))) if good.any() else float("inf")
    return (float(T[0]), float(T[1]), float(math.atan2(math.sin(T[2]), math.cos(T[2])))), fitness, rmse


def align(current_xy: np.ndarray, home_xy: np.ndarray):
    """Best of a few start guesses (placement can be off by some degrees)."""
    best = None
    for deg in (0.0, -6.0, 6.0, -12.0, 12.0):
        T, fit, rmse = icp_2d(current_xy, home_xy, init=(0.0, 0.0, math.radians(deg)))
        if best is None or fit > best[1] + 1e-6 or (abs(fit - best[1]) < 1e-6 and rmse < best[2]):
            best = (T, fit, rmse)
        if fit > 0.8 and deg == 0.0:
            break
    return best


def save_home_scan(path: str, xy: np.ndarray) -> None:
    np.savez_compressed(path, xy=np.asarray(xy, dtype=np.float32))
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass


def load_home_scan(path: str):
    if not os.path.isfile(path):
        return None
    with np.load(path) as f:
        return np.asarray(f["xy"], dtype=float)


class AlignedSensors:
    """Wraps sensors so poses and points come out in the TEACHING frame."""

    def __init__(self, sensors, T):
        self.s = sensors
        self.T = T

    def pose(self):
        p = self.s.pose()
        if p is None:
            return None
        t, x, y, z, yaw = p
        (ax, ay), = apply(self.T, np.array([[x, y]]))
        return (t, float(ax), float(ay), z, yaw + self.T[2])

    def points(self):
        pts = self.s.points()
        if pts is None or len(pts) == 0:
            return pts
        pts = np.asarray(pts, dtype=float).copy()
        pts[:, :2] = apply(self.T, pts[:, :2])
        return pts
