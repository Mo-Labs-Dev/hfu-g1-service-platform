"""
3D LiDAR map for the visitor app (and Studio).

Source, in this order:
  1. cloud3d.bin in the map folder, built from the real Session 03 FAST-LIO map
     (hfu_lab_static.pcd) with `python -m app.services.cloud3d_service PCD`
     or POST /api/map/cloud3d/build.
  2. Fallback: a 3D view generated from the 2D map (walls extruded, floor points),
     so the app works before the PCD is copied.

Binary format (little endian), sent as-is to the app:
  b"G1C3" | uint32 count | count * (int16 x_cm, int16 y_cm, int16 z_cm)
All points are in the map frame (leveled, floor at z = 0), same frame as the 2D map,
routes and the live G1 pose.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import threading

import numpy as np

MAGIC = b"G1C3"
DEFAULT_VOXEL = 0.10      # m
DEFAULT_MAX_POINTS = 90000
Z_MIN, Z_MAX = -0.15, 2.6  # crop: below floor noise, ceiling (keeps the top view clear)


# ------------------------------------------------------------------ PCD reading
def read_pcd(path: str) -> np.ndarray:
    """x, y, z (float) from an ascii / binary PCD (FAST-LIO / PCL)."""
    with open(path, "rb") as f:
        header = {}
        while True:
            line = f.readline()
            if not line:
                raise ValueError("PCD header incomplete")
            text = line.decode("ascii", "ignore").strip()
            if not text or text.startswith("#"):
                continue
            key, *vals = text.split()
            header[key.upper()] = vals
            if key.upper() == "DATA":
                break
        fields = header["FIELDS"]
        sizes = [int(s) for s in header["SIZE"]]
        types = header["TYPE"]
        counts = [int(c) for c in header.get("COUNT", ["1"] * len(fields))]
        n = int(header.get("POINTS", [0])[0]) or int(header["WIDTH"][0]) * int(header["HEIGHT"][0])
        mode = header["DATA"][0].lower()
        if mode == "ascii":
            arr = np.loadtxt(f, dtype=np.float64, ndmin=2)
            col, idx = 0, {}
            for name, c in zip(fields, counts):
                idx[name] = col
                col += c
            return arr[:, [idx["x"], idx["y"], idx["z"]]]
        if mode != "binary":
            raise ValueError(f"PCD DATA {mode} not supported (save as binary or ascii)")
        kinds = {"F": "f", "I": "i", "U": "u"}
        dt = np.dtype([(name if c == 1 else f"{name}_{k}", f"<{kinds[t]}{s}")
                       for name, s, t, c in zip(fields, sizes, types, counts)
                       for k in range(c)])
        data = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
        return np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float64)


def voxel_down(pts: np.ndarray, voxel: float) -> np.ndarray:
    keys = np.floor(pts / voxel).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return pts[np.sort(first)]


def level(pts: np.ndarray, info: dict) -> np.ndarray:
    R = np.asarray(info.get("leveling_rotation", np.eye(3)), float)
    t = np.asarray(info.get("leveling_translation", [0, 0, 0]), float)
    return pts @ R.T + t


def build_from_pcd(pcd: str, info: dict, voxel: float = DEFAULT_VOXEL,
                   max_points: int = DEFAULT_MAX_POINTS) -> np.ndarray:
    pts = read_pcd(pcd)
    pts = pts[np.isfinite(pts).all(axis=1)]
    pts = level(pts, info)
    pts = pts[(pts[:, 2] > Z_MIN) & (pts[:, 2] < Z_MAX)]
    v = voxel
    out = voxel_down(pts, v)
    while len(out) > max_points:
        v *= 1.15
        out = voxel_down(pts, v)
    return out


def build_from_grid(grid: np.ndarray, meta: dict, max_points: int = DEFAULT_MAX_POINTS) -> np.ndarray:
    """Fallback: walls extruded to 1.6 m + sparse floor, from the 2D occupancy map."""
    res = float(meta["resolution"])
    ox, oy = meta["origin"][:2]
    h = grid.shape[0]

    def cells(mask, step):
        rows, cols = np.nonzero(mask)
        keep = ((rows % step) == 0) & ((cols % step) == 0)
        rows, cols = rows[keep], cols[keep]
        return ox + (cols + 0.5) * res, oy + (h - 1 - rows + 0.5) * res

    wx, wy = cells(grid <= 50, 2)
    heights = np.arange(0.05, 1.65, 0.2)
    walls = np.stack([np.repeat(wx, len(heights)), np.repeat(wy, len(heights)),
                      np.tile(heights, len(wx))], axis=1)
    fx, fy = cells(grid >= 250, 6)
    floor = np.stack([fx, fy, np.zeros_like(fx)], axis=1)
    pts = np.concatenate([walls, floor])
    if len(pts) > max_points:
        pts = pts[np.linspace(0, len(pts) - 1, max_points).astype(int)]
    return pts


def encode(pts: np.ndarray) -> bytes:
    cm = np.clip(np.round(pts * 100.0), -32767, 32767).astype("<i2")
    return MAGIC + struct.pack("<I", len(cm)) + cm.tobytes()


def decode(blob: bytes) -> np.ndarray:
    if blob[:4] != MAGIC:
        raise ValueError("not a G1C3 cloud")
    n = struct.unpack("<I", blob[4:8])[0]
    return np.frombuffer(blob, "<i2", count=n * 3, offset=8).reshape(n, 3).astype(float) / 100.0


# ------------------------------------------------------------------ service
class Cloud3D:
    def __init__(self, map_dir: str | None = None):
        from app.services.lab_map_service import MAP_DIR
        self.map_dir = map_dir or MAP_DIR
        self._blob: bytes | None = None
        self._meta: dict = {}
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return os.path.join(self.map_dir, "cloud3d.bin")

    def _map_info(self) -> dict:
        try:
            with open(os.path.join(self.map_dir, "map_info.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _describe(self, pts: np.ndarray, source: str) -> dict:
        return {"points": int(len(pts)), "source": source,
                "min": [round(float(v), 2) for v in pts.min(axis=0)] if len(pts) else None,
                "max": [round(float(v), 2) for v in pts.max(axis=0)] if len(pts) else None}

    def blob(self) -> tuple[bytes, dict]:
        with self._lock:
            if self._blob is None:
                if os.path.isfile(self.path):
                    with open(self.path, "rb") as f:
                        self._blob = f.read()
                    self._meta = self._describe(decode(self._blob), "lidar")
                else:
                    from app.services.lab_map_service import lab_map
                    lab_map._load()
                    pts = build_from_grid(lab_map._grid, lab_map._meta)
                    self._blob = encode(pts)
                    self._meta = self._describe(pts, "2d_map")
            return self._blob, self._meta

    def info(self) -> dict:
        return self.blob()[1]

    def build(self, pcd: str | None = None, voxel: float = DEFAULT_VOXEL,
              max_points: int = DEFAULT_MAX_POINTS) -> dict:
        info = self._map_info()
        pcd = os.path.expanduser(pcd or os.getenv("G1_MAP_PCD", "") or info.get("source_pcd", ""))
        if not pcd or not os.path.isfile(pcd):
            raise FileNotFoundError(
                f"PCD not found: {pcd or '(none)'} - copy it out of the container first "
                "(see runbook) or set G1_MAP_PCD")
        pts = build_from_pcd(pcd, info, voxel, max_points)
        blob = encode(pts)
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, self.path)
        with self._lock:
            self._blob, self._meta = blob, self._describe(pts, "lidar")
        return {"ok": True, **self._meta, "pcd": pcd, "bytes": len(blob)}


cloud3d = Cloud3D()


if __name__ == "__main__":
    # python -m app.services.cloud3d_service /path/to/hfu_lab_static.pcd
    src = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(cloud3d.build(src), indent=2))
