import numpy as np

from app.services.cloud3d_service import Cloud3D, build_from_pcd, decode, encode, read_pcd


def _pcd(path, xyz):
    n = len(xyz)
    rec = np.zeros(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")])
    rec["x"], rec["y"], rec["z"] = xyz.T
    hdr = (f"VERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n"
           f"WIDTH {n}\nHEIGHT 1\nPOINTS {n}\nDATA binary\n")
    path.write_bytes(hdr.encode() + rec.tobytes())


def test_pcd_roundtrip_and_leveling(tmp_path):
    xyz = np.random.default_rng(1).uniform([-3, -3, -1.2], [3, 3, 1.0], (2000, 3)).astype("<f4")
    _pcd(tmp_path / "m.pcd", xyz)
    assert np.allclose(read_pcd(str(tmp_path / "m.pcd")), xyz, atol=1e-6)
    out = build_from_pcd(str(tmp_path / "m.pcd"), {"leveling_translation": [0, 0, 1.2]}, 0.1, 500)
    assert 0 < len(out) <= 500
    assert out[:, 2].min() > -0.15 - 1e-9
    assert np.allclose(decode(encode(out)), out, atol=0.006)


def test_fallback_from_2d_map():
    blob, meta = Cloud3D().blob()
    assert blob[:4] == b"G1C3" and meta["points"] > 1000
    assert meta["source"] in ("2d_map", "lidar")
