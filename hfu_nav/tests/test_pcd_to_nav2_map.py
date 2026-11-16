import json, os, struct, sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pcd_to_nav2_map as m

TILT_DEG = 8.0
FLOOR_Z = -1.25

def synthetic_lab(seed=1):
    rng = np.random.default_rng(seed)
    pts = []
    def box(x0, x1, y0, y1, z0, z1, n):
        pts.append(np.column_stack([rng.uniform(x0, x1, n), rng.uniform(y0, y1, n), rng.uniform(z0, z1, n)]))
    box(0, 10, 0, 6, 0, 0.01, 60000)          # floor
    box(0, 10, 0, 6, 2.8, 2.81, 40000)        # ceiling
    box(0, 10, 0, 0.05, 0, 2.8, 15000)        # walls
    box(0, 10, 5.95, 6, 0, 2.8, 15000)
    box(0, 0.05, 0, 6, 0, 2.8, 10000)
    box(9.95, 10, 0, 6, 0, 2.8, 10000)
    box(4, 6, 2, 3, 0.74, 0.76, 6000)         # table top (2 x 1 m, 0.75 m)
    for lx, ly in [(4.05, 2.05), (5.95, 2.05), (4.05, 2.95), (5.95, 2.95)]:
        box(lx - 0.03, lx + 0.03, ly - 0.03, ly + 0.03, 0, 0.74, 300)
    box(7, 7.6, 1, 1.6, 2.2, 2.8, 2000)       # lamp hanging high (must be ignored)
    xyz = np.vstack(pts)
    xyz[:, 2] += FLOOR_Z
    a = np.radians(TILT_DEG)                  # tilt around x axis
    R = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    return xyz @ R.T

def write_pcd(path, xyz, fmt):
    pts = np.column_stack([xyz, np.ones(len(xyz))]).astype(np.float32)   # x y z intensity
    hdr = ("# .PCD v0.7\nVERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\n"
           f"COUNT 1 1 1 1\nWIDTH {len(pts)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(pts)}\nDATA {fmt}\n")
    with open(path, "wb") as f:
        f.write(hdr.encode())
        if fmt == "ascii":
            f.write("\n".join(" ".join(f"{v:.5f}" for v in row) for row in pts).encode())
        elif fmt == "binary":
            f.write(pts.tobytes())
        else:  # binary_compressed: column-major + literal-only LZF
            raw = b"".join(pts[:, i].tobytes() for i in range(4))
            comp = bytearray()
            for i in range(0, len(raw), 32):
                chunk = raw[i:i + 32]
                comp.append(len(chunk) - 1); comp += chunk
            f.write(struct.pack("<II", len(comp), len(raw)) + bytes(comp))

def run(tmp_path, fmt="binary", n_points=None):
    xyz = synthetic_lab()
    src = tmp_path / "in" / "lab.pcd"; src.parent.mkdir()
    write_pcd(src, xyz if n_points is None else xyz[:n_points], fmt)
    out = tmp_path / "out"
    assert m.main([str(src), "--out", str(out)]) == 0
    info = json.loads((out / "map_info.json").read_text())
    raw = (out / "map.pgm").read_bytes()
    w, h = map(int, raw.split(b"\n")[1].split())
    img = np.frombuffer(raw[-w * h:], dtype=np.uint8).reshape(h, w)
    return info, img, out

def cell(info, img, x, y):
    """value of map cell at leveled map coordinates (x, y)."""
    res, ox, oy = info["resolution"], info["origin"][0], info["origin"][1]
    col = int((x - ox) / res); row = img.shape[0] - 1 - int((y - oy) / res)
    return img[row, col]

def leveled_xy(info, x, y):
    """synthetic room coords -> map frame coords (apply same tilt+level)."""
    a = np.radians(TILT_DEG)
    R0 = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    p = R0 @ np.array([x, y, FLOOR_Z])
    R = np.array(info["leveling_rotation"]); t = np.array(info["leveling_translation"])
    q = R @ p + t
    return q[0], q[1]

def test_binary_map_is_correct(tmp_path):
    info, img, out = run(tmp_path, "binary")
    assert abs(info["floor_tilt_deg"] - TILT_DEG) < 0.5          # tilt found
    for f in ("map.pgm", "map.yaml", "map_preview.png", "map_info.json"):
        assert (out / f).exists()
    assert (out / "map_preview.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    v = lambda x, y: cell(info, img, *leveled_xy(info, x, y))
    assert v(2.0, 4.5) == 254          # open floor -> free
    assert v(5.0, 0.02) == 0           # wall -> obstacle
    assert v(5.0, 2.5) == 0            # table top at 0.75 m -> obstacle
    assert v(7.3, 1.3) == 254          # lamp at 2.2-2.8 m ignored -> free
    yaml = (out / "map.yaml").read_text()
    assert "mode: trinary" in yaml and "resolution: 0.05" in yaml

def test_ascii_and_compressed_formats(tmp_path):
    for fmt in ("ascii", "binary_compressed"):
        d = tmp_path / fmt; d.mkdir()
        info, img, _ = run(d, fmt, n_points=None if fmt != "ascii" else None)
        assert abs(info["floor_tilt_deg"] - TILT_DEG) < 0.5
        assert info["occupied_cells"] > 500 and info["free_cells"] > 10000

def test_refuses_to_write_into_input_folder(tmp_path):
    src = tmp_path / "lab.pcd"
    write_pcd(src, synthetic_lab()[:5000], "binary")
    assert m.main([str(src), "--out", str(tmp_path)]) == 2
    assert m.main([str(src), "--out", str(tmp_path / "sub")]) == 2

def test_lzf_backreference():
    # "abcabcabc": literal "abc" then backref len 6, offset 3
    comp = bytes([2]) + b"abc" + bytes([(4 << 5) | 0, 2])
    assert m._lzf_decompress(comp, 9) == b"abcabcabc"
