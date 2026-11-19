import json, math, sys, time
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import sim_service as sim
from app.services.lab_map_service import lab_map


def free_points():
    """Two far apart, well-clear points on the real map."""
    import cv2
    pl = sim.planner()
    n, lab = cv2.connectedComponents(pl.ok.astype(np.uint8), connectivity=8)
    biggest = np.argmax(np.bincount(lab[pl.ok].ravel()))
    rs, cs = np.nonzero((lab == biggest) & (pl.clr >= 0.9))
    pts = [pl.xy(r, c) for r, c in zip(rs[::50], cs[::50])]
    a = pts[0]
    b = max(pts, key=lambda p: math.hypot(p[0] - a[0], p[1] - a[1]))
    return a, b


def test_planner_finds_safe_path():
    a, b = free_points()
    t = time.time()
    res = sim.planner().plan(a, b)
    dt = time.time() - t
    assert res["length_m"] > 5 and res["min_clearance_m"] >= 0.28
    assert dt < 10, dt


def test_planner_rejects_wall_points():
    w = lab_map.walls()[1000]
    with pytest.raises(ValueError):
        sim.planner().plan((w[0] + 50, w[1] + 50), (w[0] + 60, w[1] + 60))   # outside the map


def test_simulated_walk_reaches_goal():
    a, b = free_points()
    res = sim.planner().plan(a, b)
    path = res["path"]
    # keep the test short: first ~12 m of the planned path
    dense = sim.densify(np.asarray(path), 0.1)[:120]
    route = sim.route_from_path(dense.tolist())
    out = sim.simulate(route, "en", people=[], return_home=False)
    assert out["result"] == "done", (out["message"], out["states"][-5:])
    assert out["end_error_m"] < 0.4 and len(out["frames"]) > 10


def test_virtual_person_blocks_then_leaves():
    a, b = free_points()
    dense = sim.densify(np.asarray(sim.planner().plan(a, b)["path"]), 0.1)[:120]
    mid = dense[60]
    route = sim.route_from_path(dense.tolist())
    out = sim.simulate(route, "en", people=[{"x": float(mid[0]), "y": float(mid[1]), "t_from": 0, "t_to": 60}],
                       return_home=False)
    assert out["result"] == "done" and out["blocked_s"] > 5
    assert any("let me pass" in e[2] for e in out["events"] if e[1] == "say")


def test_tour_simulation_from_route_file(tmp_path, monkeypatch):
    a, b = free_points()
    dense = sim.densify(np.asarray(sim.planner().plan(a, b)["path"]), 0.1)[:100]
    (tmp_path / "routes").mkdir()
    yaw0 = math.atan2(dense[1][1] - dense[0][1], dense[1][0] - dense[0][0])
    route = {"name": "t", "points": [[float(x), float(y), 0.0] for x, y in dense], "start_yaw": yaw0,
             "end_yaw": yaw0, "title_en": "Test tour",
             "stops": [{"index": 40, "name": "s1", "title_en": "Printer", "text_en": "This is a printer.",
                        "yaw": yaw0 + 1.2},
                       {"index": 90, "name": "s2", "title_en": "Robot", "yaw": yaw0}]}
    json.dump(route, open(tmp_path / "routes" / "t.json", "w"))
    monkeypatch.setattr(lab_map, "routes_dir", str(tmp_path / "routes"))
    monkeypatch.setattr(lab_map, "store", str(tmp_path / "align.json"))
    lab_map.set_home(0.0, 0.0, 0.0)                     # teach frame == map frame
    r, src = sim.route_in_map("t")
    out = sim.simulate(r, "en", people=[], return_home=True)
    assert out["result"] == "done", (out["message"], out["states"][-6:])
    said = [e[2] for e in out["events"] if e[1] == "say"]
    assert "This is a printer." in said and any("Robot" in s for s in said)
    assert out["end_error_m"] < 0.5
