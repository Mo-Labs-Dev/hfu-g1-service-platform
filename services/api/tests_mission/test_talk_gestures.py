import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import talk_gestures as tg  # noqa: E402


def test_switch_and_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "FILE", str(tmp_path / "tg.json"))
    monkeypatch.setattr(tg, "_DATA", str(tmp_path))
    assert tg.enabled() is False                  # off until tested
    tg.set_enabled(True)
    assert tg.enabled() is True
    assert tg.speech_seconds("x" * 100) == 8.5
    assert tg.speech_seconds("anything", 4200) == 4.2
    assert tg.speech_seconds("x" * 100, 500) == 8.5          # bridge said 0.5 s -> text needs 8.5 s


def test_no_gesture_when_off_or_short(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "FILE", str(tmp_path / "tg.json"))
    calls = []
    monkeypatch.setattr(tg.robot_hub, "post_json", lambda *a, **k: calls.append(a) or (200, {}))
    tg.gesture_for("A long answer about the lab " * 3)          # off
    tg.set_enabled(True)
    tg.gesture_for("Yes?")                                       # too short
    import time
    time.sleep(0.1)
    assert calls == []
    tg.gesture_for("A long answer about the lab " * 3)
    time.sleep(0.2)
    assert calls and calls[0][0].endswith("/api/pick/talk")
