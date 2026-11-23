import json, sys, time
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import (activity_service as act, insights_service as ins, interaction_control as ic,
                          knowledge_service as ks, show_service as ss)


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(ic, "SETTINGS_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(ic, "_log", ic.deque(maxlen=300))
    monkeypatch.setattr(ic, "_loaded_log", False)
    monkeypatch.setattr(ic, "broadcaster", None)
    monkeypatch.setattr(act, "broadcaster", None)
    monkeypatch.setattr(act, "TRAJ_DIR", str(tmp_path / "traj"))
    monkeypatch.setattr(ss, "SHOWS_FILE", str(tmp_path / "shows.json"))
    monkeypatch.setattr(ss, "RUNS_FILE", str(tmp_path / "show_runs.jsonl"))
    kb = tmp_path / "kb.json"
    kb.write_text(json.dumps({"entries": [{"id": "ipse", "title": "HFU IPSE", "keywords": ["ipse"], "facts": "IPSE is an institute."}]}))
    monkeypatch.setattr(ks, "KNOWLEDGE_PATH", kb)
    return tmp_path


# ---------------- insights + knowledge
def test_weak_detection():
    assert ins.is_weak("I'm sorry, I don't know the opening hours.")
    assert ins.is_weak("Das weiß ich leider nicht.")
    assert not ins.is_weak("I'm G1, a humanoid robot.")


def test_questions_grouped_and_weak():
    ic.record("app", "What is IPSE?", "IPSE is an institute.", "en", 2.0)
    ic.record("mic", "Hey G1, what is IPSE", "IPSE is an institute at HFU.", "en", 3.0)
    ic.record("app", "When does the lab open?", "I don't know the opening hours.", "en", 2.5)
    ic.record("operator", "", "Welcome")
    ic.record("app", "x", "paused", note="paused")
    q = ins.questions(30)
    assert q["total"] == 3 and q["distinct"] == 2
    top = q["top"][0]
    assert top["count"] == 2 and top["sources"] == {"app": 1, "mic": 1} and top["avg_s"] == 2.5
    assert [w["question"] for w in q["weak"]] == ["When does the lab open?"]


def test_knowledge_save_backup_and_match():
    out = ins.save_knowledge([{"title": "Opening hours", "keywords": "open, opening, hours",
                               "facts": "The lab is open Monday to Friday 9 to 17."},
                              {"id": "ipse", "title": "HFU IPSE", "keywords": ["ipse"], "facts": "IPSE is an institute."}])
    assert out[0]["id"] == "opening_hours" and out[0]["keywords"] == ["open", "opening", "hours"]
    assert ks.KNOWLEDGE_PATH.with_suffix(".json.bak").exists()
    assert ins.match("When is the lab open?")[0]["title"] == "Opening hours"
    with pytest.raises(ValueError):
        ins.save_knowledge([{"title": "x", "facts": ""}])


# ---------------- show mode
class FakeHw:
    def __init__(self, fail=None, safe=True):
        self.calls, self.fail, self.safe, self.stopped = [], fail, safe, 0

    def preflight(self):
        return (True, "") if self.safe else (False, "E-stop")

    def say(self, text, lang):
        self.calls.append(("say", text, lang)); return 0.0

    def ask(self, q, lang):
        self.calls.append(("ask", q)); return "answer", 0.0

    def gesture(self, name, should_stop):
        self.calls.append(("gesture", name)); return "done"

    def walk(self, d, lang, should_stop):
        self.calls.append(("walk", d)); return "blocked for ever" if self.fail == "walk" else "done"

    def point(self, t, lang, should_stop):
        self.calls.append(("point", t)); return "done"

    def stop_motion(self):
        self.stopped += 1


def show(steps):
    return ss.clean_show({"title": "Demo", "steps": steps})


def test_clean_show_validation():
    with pytest.raises(ValueError):
        ss.clean_show({"title": "", "steps": [{"type": "wait", "seconds": 1}]})
    with pytest.raises(ValueError):
        ss.clean_show({"title": "a", "steps": [{"type": "gesture", "gesture": "backflip"}]})
    with pytest.raises(ValueError):
        ss.clean_show({"title": "a", "steps": [{"type": "wait", "seconds": 9999}]})
    s = ss.clean_show({"title": "a", "steps": [{"type": "say", "text_de": "Hallo"}, {"type": "pause"}]})
    assert s["steps"][1]["text"] == "Continue when ready"


def test_save_load_delete_example():
    assert ss.load_shows()[0]["id"] == "welcome_demo"           # example when nothing saved
    sh = ss.save_show({"title": "Open house", "steps": [{"type": "wait", "seconds": 1}]})
    assert {s["id"] for s in ss.load_shows()} == {sh["id"], "welcome_demo"}   # example kept
    ss.delete_show(sh["id"])
    with pytest.raises(KeyError):
        ss.delete_show(sh["id"])


def test_run_auto_all_steps_and_record(iso):
    hw = FakeHw()
    r = ss.ShowRunner(hw, sleep=lambda s: None)
    sh = show([{"type": "say", "text_en": "Hi", "text_de": "Hallo"}, {"type": "gesture", "gesture": "high_wave"},
               {"type": "walk", "destination": "printer"}, {"type": "point", "target": "object"},
               {"type": "ask", "question_en": "What can you do?"}, {"type": "wait", "seconds": 1}])
    r.start(sh, "auto", "de", background=False)
    assert r.state["state"] == "done" and len(r.state["log"]) == 6
    assert hw.calls[0] == ("say", "Hallo", "de") and ("walk", "printer") in hw.calls
    rec = ss.load_runs()[-1]
    assert rec["result"] == "done" and rec["steps_done"] == 6 and rec["lang"] == "de"


def test_failed_step_stops_show_and_motion():
    hw = FakeHw(fail="walk")
    r = ss.ShowRunner(hw, sleep=lambda s: None)
    r.start(show([{"type": "walk", "destination": "x"}, {"type": "say", "text_en": "never"}]), background=False)
    assert r.state["state"] == "failed" and "Step 1 failed" in r.state["message"]
    assert hw.stopped == 1 and ("say", "never", "en") not in hw.calls
    assert ss.load_runs()[-1]["failed_step"] == 0


def test_motion_refused_when_not_safe():
    hw = FakeHw(safe=False)
    r = ss.ShowRunner(hw, sleep=lambda s: None)
    r.start(show([{"type": "gesture", "gesture": "clap"}]), background=False)
    assert r.state["state"] == "failed" and "E-stop" in r.state["message"] and hw.calls == []


def test_step_mode_waits_and_stop():
    hw = FakeHw()
    r = ss.ShowRunner(hw)
    r.start(show([{"type": "say", "text_en": "one"}, {"type": "say", "text_en": "two"}]), "step")
    for _ in range(50):
        if r.state["state"] == "waiting":
            break
        time.sleep(0.02)
    assert r.state["state"] == "waiting" and len(hw.calls) == 1
    r.next()
    for _ in range(100):
        if r.state["state"] == "done":
            break
        time.sleep(0.02)
    assert r.state["state"] == "done" and len(hw.calls) == 2
    # pause step + stop
    r.start(show([{"type": "pause", "text": "questions"}, {"type": "say", "text_en": "three"}]), "auto")
    for _ in range(50):
        if r.state["state"] == "waiting":
            break
        time.sleep(0.02)
    r.stop()
    for _ in range(100):
        if r.state["state"] == "stopped":
            break
        time.sleep(0.02)
    assert r.state["state"] == "stopped" and hw.stopped == 1 and ("say", "three", "en") not in hw.calls
    with pytest.raises(RuntimeError):
        r.next()


def test_stop_when_idle_does_not_cancel_others():
    hw = FakeHw()
    r = ss.ShowRunner(hw)
    r.stop()
    assert hw.stopped == 0


# ---------------- activity tracker + trajectories
def test_tracker_events_and_trajectory(iso):
    ev, saved = [], []
    clock = {"t": 100.0}
    tr = act.Tracker(add=lambda k, t, d="", l="info": ev.append((k, t)), save=saved.append, clock=lambda: clock["t"])
    pose = lambda x, y: {"pose": {"x": x, "y": y, "yaw": 0.0}}
    tr.feed({"state": "idle"}, None, None)
    tr.feed({"state": "starting", "route": "goto:printer", "kind": "goto"}, pose(0, 0), None)
    for i in range(1, 6):
        clock["t"] += 1
        tr.feed({"state": "walking", "route": "goto:printer"}, pose(i * 0.5, 0), None)
    tr.feed({"state": "blocked", "route": "goto:printer"}, pose(2.5, 0), None)
    tr.feed({"state": "walking", "route": "goto:printer"}, pose(3.0, 0), None)
    tr.feed({"state": "arrived", "route": "goto:printer"}, pose(3.2, 0), None)
    clock["t"] += 1
    tr.feed({"state": "done", "route": "goto:printer"}, pose(3.2, 0), None)
    texts = [t for _, t in ev]
    assert texts[0] == "Walking to printer" and "Path blocked – waiting" in texts
    assert "Path free again – walking on" in texts and texts[-1] == "Walk finished"
    assert len(saved) == 1 and saved[0]["result"] == "done" and saved[0]["blocked"] == [[2.5, 0.0]]
    assert abs(saved[0]["length_m"] - 3.2) < 1e-6 and saved[0]["duration_s"] == 6.0


def test_trajectory_files_roundtrip():
    name = act.save_trajectory({"started": "2026-11-23T15:00:00", "route": "goto:printer", "result": "done",
                                "samples": [[0, 0, 0, 0, "walking"], [1, 1, 0, 0, "walking"]], "blocked": [],
                                "duration_s": 1, "length_m": 1.0})
    lst = act.list_trajectories()
    assert lst[0]["id"] == name and lst[0]["route"] == "printer"
    assert act.get_trajectory(name)["length_m"] == 1.0
    with pytest.raises(KeyError):
        act.get_trajectory("../../etc/passwd")


def test_interaction_record_adds_activity_event():
    before = len(act.recent())
    ic.record("mic", "what is this lab", "This is the IPSE lab.")
    assert len(act.recent()) == before + 1 and act.recent()[-1]["kind"] == "talk"


# ---------------- evaluation summary
def test_evaluation_summary_and_csv(iso, monkeypatch):
    from app.services import evaluation_service as ev, runs_service
    runs = iso / "runs.jsonl"
    runs.write_text(json.dumps({"started": "2026-11-23T10:00:00", "route": "goto:printer", "kind": "goto",
                                "result": "done", "duration_s": 40, "length_m": 8}) + "\n")
    monkeypatch.setattr(runs_service, "RUNS_FILE", str(runs))
    monkeypatch.setattr(runs_service, "META_FILE", str(iso / "meta.json"))
    monkeypatch.setattr(runs_service.load_runs, "__defaults__", (str(runs),))
    pts = iso / "points.jsonl"
    pts.write_text("\n".join(json.dumps(r) for r in [
        {"started": "2026-11-23T11:00:00", "target": "object", "side": "left", "result": "done", "duration_s": 20},
        {"started": "2026-11-23T11:05:00", "target": "object", "side": "right", "result": "too_far", "duration_s": 5}]))
    monkeypatch.setattr(ev, "POINT_RUNS_FILE", str(pts))
    ic.record("app", "Who are you?", "I'm G1.", "en", 1.0)
    ic.record("mic", "what time is it", "I don't know.", "de", 3.0)
    r = ss.ShowRunner(FakeHw(), sleep=lambda s: None)
    r.start(show([{"type": "say", "text_en": "hi"}]), background=False)
    s = ev.summary(0)
    c = s["conversations"]
    assert c["total"] == 2 and c["by_source"]["mic"] == 1 and c["weak_rate"] == 0.5 and c["answer_s_all"]["mean"] == 2.0
    assert s["walks"]["autonomous_goto"]["done"] == 1
    assert s["points"]["success_rate"] == 0.5 and s["points"]["by_target"]["object"]["runs"] == 2
    assert s["shows"]["runs"] == 1 and s["shows"]["success_rate"] == 1.0
    assert len(s["daily"]) == 14
    csv_text = ev.export("conversations")
    assert csv_text.splitlines()[0].startswith("id,t,source") and "True" in csv_text
    with pytest.raises(KeyError):
        ev.export("nope")
