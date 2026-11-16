#!/usr/bin/env python3
"""
Convert a FAST-LIO 3D point-cloud map (.pcd) into a 2D occupancy map for
Nav2 (map.pgm + map.yaml) plus a preview image.

READ-ONLY on the input map. Writes only into --out (a NEW folder).

    python3 pcd_to_nav2_map.py \
        /ros2_ws/maps/hfu_lab_full/session_03/hfu_lab_static.pcd \
        --out /ros2_ws/maps/hfu_lab_full/nav2d_session03

What it does:
  1. Reads the PCD (ascii, binary or binary_compressed) with numpy only.
  2. Finds the floor plane (RANSAC) and levels the map, because a
     head-mounted MID-360 often gives a slightly tilted map.
  3. Points between --min-height and --max-height above the floor become
     obstacles (default 0.10 - 1.60 m: G1 body + arms).
  4. Cells where the floor was seen become free; everything else unknown.
  5. Saves map.pgm / map.yaml (Nav2 map_server, trinary) and
     map_preview.png, plus map_info.json with the leveling transform
     (needed later so 3D localization and this 2D map share one frame).

Requires: numpy (already in the g1pilot-dev container).
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import zlib

import numpy as np

# ----------------------------------------------------------------------
# PCD reader
# ----------------------------------------------------------------------

_PCD_TYPES = {("F", 4): "f4", ("F", 8): "f8",
              ("I", 1): "i1", ("I", 2): "i2", ("I", 4): "i4", ("I", 8): "i8",
              ("U", 1): "u1", ("U", 2): "u2", ("U", 4): "u4", ("U", 8): "u8"}


def _lzf_decompress(data: bytes, out_len: int) -> bytes:
    """LZF decompression (used by PCL binary_compressed)."""
    out = bytearray(out_len)
    ip = op = 0
    n = len(data)
    while ip < n:
        ctrl = data[ip]
        ip += 1
        if ctrl < 32:                      # literal run
            ln = ctrl + 1
            out[op:op + ln] = data[ip:ip + ln]
            ip += ln
            op += ln
        else:                              # back reference
            ln = ctrl >> 5
            ref = op - ((ctrl & 0x1F) << 8) - 1
            if ln == 7:
                ln += data[ip]
                ip += 1
            ref -= data[ip]
            ip += 1
            ln += 2
            for _ in range(ln):            # may overlap -> byte by byte
                out[op] = out[ref]
                op += 1
                ref += 1
    if op != out_len:
        raise ValueError(f"LZF size mismatch ({op} != {out_len})")
    return bytes(out)


def read_pcd_xyz(path: str) -> np.ndarray:
    """Return an (N, 3) float64 array of x, y, z. NaNs removed."""
    with open(path, "rb") as f:
        header = {}
        while True:
            line = f.readline()
            if not line:
                raise ValueError("PCD header ended unexpectedly")
            text = line.decode("ascii", errors="replace").strip()
            if not text or text.startswith("#"):
                continue
            key, _, value = text.partition(" ")
            header[key.upper()] = value.split()
            if key.upper() == "DATA":
                break
        body = f.read()

    fields = header["FIELDS"]
    sizes = [int(s) for s in header["SIZE"]]
    types = header["TYPE"]
    counts = [int(c) for c in header.get("COUNT", ["1"] * len(fields))]
    points = int(header.get("POINTS", header.get("WIDTH"))[0])
    fmt = header["DATA"][0].lower()
    for axis in ("x", "y", "z"):
        if axis not in fields:
            raise ValueError(f"PCD has no '{axis}' field (fields: {fields})")

    if fmt == "ascii":
        rows = np.loadtxt(body.decode().splitlines(), dtype=np.float64, ndmin=2)
        cols = []
        col = 0
        for name, cnt in zip(fields, counts):
            cols.append((name, col))
            col += cnt
        idx = {name: c for name, c in cols}
        xyz = rows[:, [idx["x"], idx["y"], idx["z"]]]

    elif fmt == "binary":
        dtype = np.dtype([(f if c == 1 else f, _PCD_TYPES[(t, s)], (c,) if c > 1 else ())
                          for f, s, t, c in zip(fields, sizes, types, counts)])
        arr = np.frombuffer(body[:dtype.itemsize * points], dtype=dtype, count=points)
        xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float64)

    elif fmt == "binary_compressed":
        comp_size, raw_size = struct.unpack("<II", body[:8])
        raw = _lzf_decompress(body[8:8 + comp_size], raw_size)
        # Data is stored field by field (column-major).
        offset = 0
        columns = {}
        for name, s, t, c in zip(fields, sizes, types, counts):
            n_bytes = s * c * points
            col = np.frombuffer(raw[offset:offset + n_bytes],
                                dtype=_PCD_TYPES[(t, s)]).reshape(points, c)
            columns[name] = col[:, 0]
            offset += n_bytes
        xyz = np.stack([columns["x"], columns["y"], columns["z"]], axis=1).astype(np.float64)
    else:
        raise ValueError(f"Unsupported PCD DATA format '{fmt}'")

    return xyz[np.isfinite(xyz).all(axis=1)]


# ----------------------------------------------------------------------
# Floor detection and leveling
# ----------------------------------------------------------------------

def fit_floor_plane(xyz: np.ndarray, max_tilt_deg: float = 30.0,
                    iterations: int = 400, tolerance: float = 0.04,
                    seed: int = 0) -> tuple[np.ndarray, float, int]:
    """
    RANSAC: among near-horizontal planes, take the large one that is
    LOWEST (floor, not ceiling or table tops).
    Returns (unit normal pointing up, d) with n.p + d = 0, and inlier count.
    """
    rng = np.random.default_rng(seed)
    sample = xyz if len(xyz) <= 80000 else xyz[rng.choice(len(xyz), 80000, replace=False)]
    cos_max = np.cos(np.radians(max_tilt_deg))
    candidates = []
    for _ in range(iterations):
        p = sample[rng.choice(len(sample), 3, replace=False)]
        n = np.cross(p[1] - p[0], p[2] - p[0])
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n /= norm
        if n[2] < 0:
            n = -n
        if n[2] < cos_max:                       # not horizontal enough
            continue
        d = -n.dot(p[0])
        dist = sample @ n + d
        inliers = np.abs(dist) < tolerance
        count = int(inliers.sum())
        if count < 0.03 * len(sample):
            continue
        height = float(-d)                        # plane height along n
        candidates.append((count, height, n, d))
    if not candidates:
        raise RuntimeError("No floor plane found. Try --no-level / --floor-z.")
    best_count = max(c[0] for c in candidates)
    # Big planes (>= 40% of the biggest) - choose the lowest one = floor.
    big = [c for c in candidates if c[0] >= 0.4 * best_count]
    count, _, n, d = min(big, key=lambda c: c[1])

    # Refine with least squares on all inliers.
    dist = sample @ n + d
    inl = sample[np.abs(dist) < tolerance]
    centroid = inl.mean(axis=0)
    _, _, vt = np.linalg.svd(inl - centroid, full_matrices=False)
    n = vt[2] if vt[2][2] > 0 else -vt[2]
    d = -n.dot(centroid)
    return n, float(d), int((np.abs(sample @ n + d) < tolerance).sum())


def leveling_transform(n: np.ndarray, d: float) -> tuple[np.ndarray, np.ndarray]:
    """Rotation R and translation t so that floor -> z = 0, normal -> +z."""
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(n, z)
    s = np.linalg.norm(v)
    c = float(n.dot(z))
    if s < 1e-9:
        R = np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)
    # A floor point p satisfies n.p = -d ; after rotation its z = -d.
    t = np.array([0.0, 0.0, d])
    return R, t


# ----------------------------------------------------------------------
# Occupancy grid
# ----------------------------------------------------------------------

def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r:
                continue
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def build_grid(xyz: np.ndarray, resolution: float, min_h: float, max_h: float,
               floor_band: float, min_points: int, margin: float):
    z = xyz[:, 2]
    obstacle = xyz[(z > min_h) & (z < max_h)]
    floor = xyz[np.abs(z) < floor_band]
    if len(floor) == 0:
        raise RuntimeError("No floor points after leveling. Check --floor-z.")

    ref = np.vstack([floor[:, :2], obstacle[:, :2]]) if len(obstacle) else floor[:, :2]
    lo = np.percentile(ref, 0.05, axis=0) - margin   # ignore a few far outliers
    hi = np.percentile(ref, 99.95, axis=0) + margin
    width = int(np.ceil((hi[0] - lo[0]) / resolution))
    height = int(np.ceil((hi[1] - lo[1]) / resolution))

    def to_cells(pts):
        ij = np.floor((pts[:, :2] - lo) / resolution).astype(np.int64)
        ok = (ij[:, 0] >= 0) & (ij[:, 0] < width) & (ij[:, 1] >= 0) & (ij[:, 1] < height)
        return ij[ok]

    occ_count = np.zeros((height, width), dtype=np.int32)
    ij = to_cells(obstacle)
    np.add.at(occ_count, (ij[:, 1], ij[:, 0]), 1)
    occupied = occ_count >= min_points

    seen_floor = np.zeros((height, width), dtype=bool)
    ij = to_cells(floor)
    seen_floor[ij[:, 1], ij[:, 0]] = True
    free = _dilate(seen_floor, 1) & ~occupied

    # Image rows go top-down; map y goes up -> flip vertically.
    img = np.full((height, width), 205, dtype=np.uint8)   # unknown
    img[free] = 254
    img[occupied] = 0
    img = np.flipud(img)
    origin = [float(lo[0]), float(lo[1]), 0.0]
    stats = {
        "cells": int(width * height),
        "occupied_cells": int(occupied.sum()),
        "free_cells": int(free.sum()),
        "size_m": [round(width * resolution, 2), round(height * resolution, 2)],
        "obstacle_points": int(len(obstacle)),
        "floor_points": int(len(floor)),
    }
    return img, origin, stats


# ----------------------------------------------------------------------
# Writers
# ----------------------------------------------------------------------

def write_pgm(path: str, img: np.ndarray) -> None:
    h, w = img.shape
    with open(path, "wb") as f:
        f.write(f"P5\n{w} {h}\n255\n".encode())
        f.write(img.tobytes())


def write_png(path: str, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def preview_rgb(img: np.ndarray, origin, resolution: float) -> np.ndarray:
    rgb = np.empty(img.shape + (3,), dtype=np.uint8)
    rgb[img == 205] = (225, 230, 227)     # unknown: light grey
    rgb[img == 254] = (255, 255, 255)     # free: white
    rgb[img == 0] = (8, 123, 57)          # obstacle: HFU green
    # 1 m grid lines + red cross at the map origin (where FAST-LIO started)
    h, w = img.shape
    step = int(round(1.0 / resolution))
    x0 = int(round(-origin[0] / resolution))
    y0 = h - 1 - int(round(-origin[1] / resolution))
    for x in range(x0 % step, w, step):
        rgb[:, x] = (rgb[:, x] * 0.85).astype(np.uint8)
    for y in range(y0 % step, h, step):
        rgb[y, :] = (rgb[y, :] * 0.85).astype(np.uint8)
    for k in range(-6, 7):
        for (yy, xx) in ((y0 + k, x0), (y0, x0 + k)):
            if 0 <= yy < h and 0 <= xx < w:
                rgb[yy, xx] = (220, 30, 30)
    return rgb


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcd")
    ap.add_argument("--out", required=True, help="NEW output folder")
    ap.add_argument("--name", default="map")
    ap.add_argument("--resolution", type=float, default=0.05)
    ap.add_argument("--min-height", type=float, default=0.10)
    ap.add_argument("--max-height", type=float, default=1.60)
    ap.add_argument("--floor-band", type=float, default=0.06)
    ap.add_argument("--min-points", type=int, default=3)
    ap.add_argument("--no-level", action="store_true",
                    help="do not fit/level the floor (use --floor-z)")
    ap.add_argument("--floor-z", type=float, default=None,
                    help="floor height in the PCD frame (only with --no-level)")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.pcd)
    out = os.path.abspath(args.out)
    if os.path.dirname(src) == out or out.startswith(os.path.dirname(src) + os.sep):
        print("Refusing to write inside the input map folder. Choose another --out.")
        return 2
    os.makedirs(out, exist_ok=True)

    t0 = time.time()
    print(f"Reading {src} ...")
    xyz = read_pcd_xyz(src)
    print(f"  {len(xyz):,} points  ({time.time() - t0:.1f} s)")

    if args.no_level:
        floor_z = args.floor_z if args.floor_z is not None else float(np.percentile(xyz[:, 2], 2))
        R, t = np.eye(3), np.array([0.0, 0.0, -floor_z])
        tilt = 0.0
        print(f"  no leveling, floor z = {floor_z:.3f} m")
    else:
        n, d, inliers = fit_floor_plane(xyz)
        R, t = leveling_transform(n, d)
        tilt = float(np.degrees(np.arccos(np.clip(n[2], -1, 1))))
        print(f"  floor plane: normal {np.round(n, 4)}, tilt {tilt:.2f} deg, "
              f"height {-d:.3f} m, {inliers:,} sample inliers")
    leveled = xyz @ R.T + t

    img, origin, stats = build_grid(leveled, args.resolution, args.min_height,
                                    args.max_height, args.floor_band,
                                    args.min_points, margin=1.0)

    pgm = os.path.join(out, f"{args.name}.pgm")
    write_pgm(pgm, img)
    with open(os.path.join(out, f"{args.name}.yaml"), "w") as f:
        f.write(f"image: {args.name}.pgm\n"
                f"mode: trinary\n"
                f"resolution: {args.resolution}\n"
                f"origin: [{origin[0]:.4f}, {origin[1]:.4f}, 0.0]\n"
                f"negate: 0\n"
                f"occupied_thresh: 0.65\n"
                f"free_thresh: 0.25\n")
    rgb = preview_rgb(img, origin, args.resolution)
    scale = max(1, min(6, 1400 // max(rgb.shape[:2])))   # enlarge small maps
    rgb = rgb.repeat(scale, axis=0).repeat(scale, axis=1)
    write_png(os.path.join(out, f"{args.name}_preview.png"), rgb)
    info = {
        "source_pcd": src,
        "points": int(len(xyz)),
        "resolution": args.resolution,
        "obstacle_band_m": [args.min_height, args.max_height],
        "floor_tilt_deg": round(tilt, 3),
        "leveling_rotation": R.round(6).tolist(),
        "leveling_translation": t.round(6).tolist(),
        "note": "map frame = PCD frame rotated by R then shifted by t "
                "(floor at z=0). Use the same transform for 3D localization.",
        "origin": origin,
        **stats,
    }
    with open(os.path.join(out, f"{args.name}_info.json"), "w") as f:
        json.dump(info, f, indent=2)

    print(f"  map {stats['size_m'][0]} x {stats['size_m'][1]} m, "
          f"{stats['occupied_cells']:,} obstacle / {stats['free_cells']:,} free cells")
    print(f"Written to {out}:  {args.name}.pgm  {args.name}.yaml  "
          f"{args.name}_preview.png  {args.name}_info.json   ({time.time() - t0:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
