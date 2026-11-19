import json, math, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from route_core import Route, RouteRecorder
from test_guide_runner import World, runner


def loop_tour(close=True):
    """Teach a 4 m x 3 m loop; stop 1 facing left (exhibit on a wall), stop 2 straight."""
    rec = RouteRecorder("lab_tour")
    for i in range(41):                       # 4 m east
        rec.add(i * 0.1, 0.0, 0.0, 0.0)
    rec.latest = (4.0, 0.0, 0.0, math.pi / 2)  # turned to face the exhibit
    rec.mark_stop("3d_printer")
    for i in range(1, 31):                    # 3 m north
        rec.add(4.0, i * 0.1, 0.0, math.pi / 2)
    rec.mark_stop("robot arm")
    if close:
        for i in range(1, 41):                # 4 m west
            rec.add(4.0 - i * 0.1, 3.0, 0.0, math.pi)
        for i in range(1, 31):                # 3 m south, back on HOME
            rec.add(0.0, 3.0 - i * 0.1, 0.0, -math.pi / 2)
        rec.latest = (0.0, 0.0, 0.0, 0.0)
    r = rec.finish(title_en="HFU lab tour", title_de="HFU Laborführung")
    r.stops[0].update(title_en="3D printer", text_en="This is our 3D printer.", text_de="Das ist unser 3D-Drucker.")
    return r


def test_recorder_marks_stops_and_saves(tmp_path):
    r = loop_tour()
    assert [s["name"] for s in r.stops] == ["3d_printer", "robot_arm"]
    assert abs(r.stops[0]["yaw"] - math.pi / 2) < 1e-3
    assert r.is_tour and r.is_loop
    r2 = Route.load(r.save(str(tmp_path)))
    assert r2.stops == r.stops


def test_old_route_files_still_load(tmp_path):
    d = {"name": "x", "points": [[0, 0, 0], [1, 0, 0]], "start_yaw": 0, "end_yaw": 0}
    (tmp_path / "x.json").write_text(json.dumps(d))
    r = Route.load(str(tmp_path / "x.json"))
    assert r.stops == [] and not r.is_tour


def test_stops_too_close_rejected():
    rec = RouteRecorder("t")
    for i in range(11):
        rec.add(i * 0.1, 0, 0, 0)
    rec.mark_stop("a")
    rec.add(1.1, 0, 0, 0)
    with pytest.raises(ValueError):
        rec.mark_stop("b")


def test_loop_tour_explains_every_stop_and_ends_home():
    w = World(); g = runner(w)
    assert g.run(loop_tour(), "en") == "done"
    states = [h[1] for h in g.status.history]
    assert states.count("explaining") == 2
    assert "returning" not in states                         # loop: no extra way back
    assert any("Welcome to the HFU lab tour" in s for s in w.said)
    assert "This is our 3D printer." in w.said                # custom text
    assert any("Here you can see the robot arm" in s for s in w.said)   # default text
    assert any("Thank you for visiting" in s for s in w.said)
    assert math.hypot(w.x, w.y) < 0.35 and abs(w.yaw) < math.radians(12)
    assert w.events == ["begin", "end"]


def test_faces_exhibit_while_explaining():
    w = World(); g = runner(w)
    yaws = []
    orig = g._say
    def say(key, lang, title="", custom=""):
        if key == "stop":
            yaws.append(w.yaw)
        return orig(key, lang, title, custom)
    g._say = say
    g.run(loop_tour(), "en")
    assert abs(yaws[0] - math.pi / 2) < math.radians(12)


def test_german_tour():
    w = World(); g = runner(w)
    g.run(loop_tour(), "de")
    assert "Das ist unser 3D-Drucker." in w.said
    assert any("Laborführung" in s for s in w.said)


def test_open_tour_walks_back_home():
    w = World(); g = runner(w)
    assert g.run(loop_tour(close=False), "en", return_home=True) == "done"
    assert "returning" in [h[1] for h in g.status.history]
    assert math.hypot(w.x, w.y) < 0.35


def test_cancel_during_explanation():
    w = World(); g = runner(w)
    orig = w.sleep
    def sleep(dt):
        orig(dt)
        if g.status.state == "explaining":
            g.cancel()
    g.sleep = sleep
    assert g.run(loop_tour(), "en") == "cancelled"
    assert w.events[-1] == "end" and w.v == 0.0


def test_status_shows_stop_progress():
    w = World(); g = runner(w)
    seen = []
    orig = w.sleep
    def sleep(dt):
        orig(dt); seen.append(g.snapshot())
    g.sleep = sleep
    g.run(loop_tour(), "en")
    exp = [s for s in seen if s["state"] == "explaining"]
    assert exp[0]["stop_index"] == 1 and exp[0]["stop_count"] == 2
    assert exp[0]["stop_title"] == "3D printer" and exp[0]["kind"] == "tour"
    progress = [s["progress"] for s in seen]
    assert progress == sorted(progress)                      # never jumps back


def test_guide_turns_at_tested_speed_even_if_joystick_is_faster():
    from route_core import FollowParams, Follower
    fast = FollowParams(max_yaw_rate=0.8)          # teleop server --max-yaw 0.8
    f = Follower(loop_tour(), fast)
    assert abs(f.turn_norm * 0.8 - 0.21) < 1e-9     # still 0.21 rad/s in place
    w = World(); w.p = fast; g = runner(w)
    assert g.run(loop_tour(), "en") == "done"
    assert math.hypot(w.x, w.y) < 0.35


def test_every_run_is_logged():
    w = World(); g = runner(w)
    log = []
    g.run_logger = log.append
    g.run(loop_tour(), "de")
    r = log[-1]
    assert r["route"] == "lab_tour" and r["kind"] == "tour" and r["result"] == "done"
    assert r["lang"] == "de" and r["stops"] == 2 and r["duration_s"] > 10 and r["length_m"] > 13
    assert r["blocked_count"] == 0 and "started" in r


def test_blocked_time_and_place_logged():
    from test_route_core import l_route
    w = World(); w.obstacle = (1005.0, 1017.0); g = runner(w)
    log = []
    g.run_logger = log.append
    g.run(l_route(), "en", return_home=False)
    r = log[-1]
    assert r["result"] == "done" and r["blocked_count"] >= 1 and r["blocked_s"] > 5
    assert len(r["blocked_at"][0]) == 2
