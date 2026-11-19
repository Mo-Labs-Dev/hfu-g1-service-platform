import json, math, os, sys, tempfile
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.lab_map_service import LabMap, compose, apply_pose
from app.services import home_align

MAP = str(Path(__file__).resolve().parents[1] / "data" / "maps" / "nav2d_session03")


def lm(tmp):
    return LabMap(MAP, str(tmp / "routes"), str(tmp / "align.json"))


def test_map_loads(tmp_path):
    m = lm(tmp_path)
    i = m.info()
    assert abs(i["width_m"] - 31.35) < 0.1 and abs(i["height_m"] - 49.15) < 0.1
    assert len(m.walls()) > 10000


def test_route_alignment_finds_home_on_map(tmp_path):
    m = lm(tmp_path)
    walls = m.walls()
    # pick a HOME in a free spot with many walls around: centre of the walls cloud
    hx, hy = np.median(walls, axis=0)
    true = (hx + 0.3, hy - 0.2, math.radians(12))      # real teach->map transform
    # HOME scan = walls within 12 m of HOME, expressed in the teaching frame
    near = walls[np.hypot(walls[:, 0] - true[0], walls[:, 1] - true[1]) < 12]
    tx, ty, th = true
    c, s = math.cos(-th), math.sin(-th)
    scan = (near - [tx, ty]) @ np.array([[c, s], [-s, c]])
    (tmp_path / "routes").mkdir()
    home_align.save_home_scan(str(tmp_path / "routes" / "t.home.npz"), scan)
    json.dump({"name": "t", "points": [[0, 0, 0], [1, 0, 0], [2, 0, 0]], "stops": [
        {"index": 2, "name": "printer", "title_en": "3D printer", "yaw": 0.0}]},
        open(tmp_path / "routes" / "t.json", "w"))
    m.set_home(hx, hy, math.radians(5))                  # operator's rough placement
    r = m.align_route("t")
    assert r["ok"] and abs(r["tx"] - true[0]) < 0.05 and abs(r["ty"] - true[1]) < 0.05
    assert abs(math.degrees(r["theta"]) - 12) < 0.5
    routes = m.routes()
    assert routes[0]["alignment"]["source"] == "scan"
    st = routes[0]["stops"][0]["map"]
    exp = apply_pose(true, (2, 0, 0))
    assert abs(st[0] - exp[0]) < 0.06 and abs(st[1] - exp[1]) < 0.06


def test_live_pose_frames(tmp_path):
    m = lm(tmp_path)
    m.set_home(1.0, 2.0, math.pi / 2)
    p = m.live_pose({"session": [1.0, 0.0, 0.0], "aligned": None, "route": None})
    assert abs(p["x"] - 1.0) < 1e-6 and abs(p["y"] - 3.0) < 1e-6 and p["source"] == "home"


def test_compose():
    a, b = (1, 0, math.pi / 2), (1, 0, 0)
    x, y, t = compose(a, b)
    assert abs(x - 1) < 1e-9 and abs(y - 1) < 1e-9


def test_tour_editing(tmp_path):
    m = lm(tmp_path)
    (tmp_path / "routes").mkdir()
    route = {"name": "tour", "title_en": "Lab tour", "points": [[0, 0, 0], [1, 0, 0]],
             "stops": [{"index": 1, "name": "a", "title_en": "A"}, {"index": 1, "name": "b"}]}
    json.dump(route, open(tmp_path / "routes" / "tour.json", "w"))
    m.update_stop("tour", "a", {"title_de": "Drucker", "text_en": "Hello. " * 200, "title_en": None})
    m.update_route("tour", {"intro_en": "Welcome!", "title_de": "Laborführung"})
    m.delete_stop("tour", "b")
    d = json.load(open(tmp_path / "routes" / "tour.json"))
    assert d["stops"][0]["title_de"] == "Drucker" and d["stops"][0]["title_en"] == "A"
    assert len(d["stops"][0]["text_en"]) == 600 and len(d["stops"]) == 1
    assert d["arrival_en"] == "Welcome!" and d["title_de"] == "Laborführung"
    r = m.routes()[0]
    assert r["intro_en"] == "Welcome!" and r["stops"][0]["title_de"] == "Drucker"
    with pytest.raises(KeyError):
        m.update_stop("tour", "zzz", {})
    with pytest.raises(ValueError):
        m.update_stop("../etc", "a", {})
