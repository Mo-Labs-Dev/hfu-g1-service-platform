import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.attract_service import DEFAULT, AttractLogic, load, save
from app.services import attract_service


def person(h):
    return {"label": "person", "confidence": 0.8, "bbox": {"y1": 100, "y2": 100 + h}}


def test_person_size_filter():
    lg = AttractLogic()
    assert lg.person_in([person(400)], 1080, 0.25)
    assert not lg.person_in([person(150)], 1080, 0.25)          # far away
    assert not lg.person_in([{"label": "chair", "confidence": 0.9, "bbox": {"y1": 0, "y2": 900}}], 1080, 0.25)


def test_greets_after_two_frames_then_cooldown():
    t = [0.0]
    lg = AttractLogic(clock=lambda: t[0])
    cfg = dict(DEFAULT, enabled=True, cooldown_s=120)
    assert not lg.step(cfg, True, "", True)
    assert lg.step(cfg, True, "", True)                          # 2nd frame -> greet
    t[0] = 60
    assert not lg.step(cfg, True, "", True) and not lg.step(cfg, True, "", True)
    assert lg.state.startswith("cooldown")
    t[0] = 200
    # same person still there -> no second greeting
    for _ in range(5):
        assert not lg.step(cfg, True, "", True)
    assert lg.state == "waiting for new visitors"
    # nobody for ~10 s, then a new visitor arrives
    for _ in range(6):
        lg.step(cfg, True, "", False)
    assert not lg.step(cfg, True, "", True)
    assert lg.step(cfg, True, "", True) and lg.greetings_today == 2


def test_paused_when_busy_or_off():
    lg = AttractLogic()
    cfg = dict(DEFAULT, enabled=True)
    for _ in range(5):
        assert not lg.step(cfg, False, "guide running", True)
    assert lg.state == "paused: guide running"
    assert not lg.step(dict(DEFAULT, enabled=False), True, "", True) and lg.state == "off"


def test_settings_clamped(tmp_path, monkeypatch):
    monkeypatch.setattr(attract_service, "SETTINGS_FILE", str(tmp_path / "a.json"))
    assert load()["enabled"] is False
    c = save({"enabled": True, "cooldown_s": 5, "min_box_height": 3, "languages": ["fr"], "text_en": ""})
    assert c["enabled"] and c["cooldown_s"] == 30 and c["min_box_height"] == 0.9
    assert c["languages"] == ["en"] and c["text_en"] == DEFAULT["text_en"]
