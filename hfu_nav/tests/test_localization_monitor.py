import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localization_monitor as lm
import pcd_to_nav2_map as m
from test_pcd_to_nav2_map import synthetic_lab, write_pcd

def walk(rec, t0, n, accept_every=0.5, fail_from=None, fail_to=None):
    t = t0
    for i in range(n):
        t = t0 + i * 0.1
        if abs((t - t0) % accept_every) < 1e-6 or i % 5 == 0:
            failing = fail_from is not None and fail_from <= t < fail_to
            rec.on_status(t, {"state": "rejected_quality", "fitness": 0.5, "rmse": 0.4} if failing
                          else {"state": "accepted", "fitness": 0.98, "rmse": 0.05})
        rec.on_pose(t, 1.0 + i * 0.05, 2.0, 0.0)
    return t

def test_pass_when_always_localized():
    rec = lm.Recorder()
    rec.on_status(0.0, {"state": "waiting_initial_pose"})   # before sim clock
    rec.on_status(5.0, {"state": "initializing"})
    walk(rec, 6.0, 400)
    s = rec.summary()
    assert s["verdict"] == "PASS"
    assert s["route_localized_percent"] > 98
    assert s["rmse_median_m"] == 0.05 and s["acceptance_percent"] == 100.0
    assert s["time_to_first_match_s"] == 1.0

def test_gap_is_detected_and_fails_pass():
    rec = lm.Recorder()
    walk(rec, 0.0, 400, fail_from=10.0, fail_to=25.0)    # 15 s lost
    s = rec.summary()
    assert s["verdict"] != "PASS"
    assert s["longest_gap_without_match_s"] >= 14
    assert s["status_counts"]["rejected_quality"] > 0

def test_outputs_and_route_png(tmp_path):
    src = tmp_path / "in" / "lab.pcd"; src.parent.mkdir()
    write_pcd(src, synthetic_lab(), "binary")
    mapdir = tmp_path / "map"
    assert m.main([str(src), "--out", str(mapdir)]) == 0
    rec = lm.Recorder()
    walk(rec, 0.0, 300, fail_from=12.0, fail_to=18.0)
    out = tmp_path / "result"
    s = lm.write_outputs(rec, str(out), str(mapdir))
    assert (out / "localization_route.png").read_bytes()[:4] == b"\x89PNG"
    assert json.loads((out / "localization_summary.json").read_text())["verdict"] == s["verdict"]
    lines = (out / "localization_log.csv").read_text().splitlines()
    assert lines[0].startswith("t,kind,state") and len(lines) > 300

def test_no_data():
    assert lm.Recorder().summary()["verdict"] == "NO DATA"
