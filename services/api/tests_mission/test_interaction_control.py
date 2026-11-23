import json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import interaction_control as ic


@pytest.fixture(autouse=True)
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "SETTINGS_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(ic, "LOG_FILE", str(tmp_path / "log.jsonl"))
    monkeypatch.setattr(ic, "_log", ic.deque(maxlen=300))
    monkeypatch.setattr(ic, "_loaded_log", False)
    monkeypatch.setattr(ic, "_seq", 0)
    events = []
    monkeypatch.setattr(ic, "broadcaster", events.append)
    return events


def test_settings_defaults_save_validate():
    s = ic.load_settings()
    assert s["app_talk"] and s["speak_answers"] and s["reply_length"] == "normal" and s["note"] == ""
    s2 = ic.save_settings({"app_talk": False, "reply_length": "short", "note": "  Open   house today "})
    assert s2["app_talk"] is False and s2["speak_answers"] is True and s2["note"] == "Open house today"
    assert ic.load_settings() == s2
    with pytest.raises(ValueError):
        ic.save_settings({"reply_length": "huge"})
    with pytest.raises(ValueError):
        ic.save_settings({"note": "x" * (ic.NOTE_MAX + 1)})


def test_prompt_extras():
    msgs, tokens = ic.prompt_extras()
    assert tokens == 250 and len(msgs) == 1
    ic.save_settings({"reply_length": "long", "note": "Invite people to station 3"})
    msgs, tokens = ic.prompt_extras()
    assert tokens == 400 and "station 3" in msgs[1]["content"]


def test_record_log_stats_and_broadcast(files):
    ic.record("app", "Hello", "Hi there", "en", 2.0, spoke=True)
    ic.record("mic", "Hey G1 what is this lab", "This is the IPSE lab.", "en", 3.0, spoke=True)
    ic.record("operator", "", "Welcome everyone", "de")
    ic.record("bogus", "q", "a")                       # unknown source -> app
    items = ic.recent()
    assert [e["id"] for e in items] == [1, 2, 3, 4] and items[3]["source"] == "app"
    st = ic.stats()
    assert st["today"] == 4 and st["by_source"]["mic"] == 1 and st["avg_answer_s"] == 2.5
    assert any(e["type"] == "interaction" for e in files)
    lines = Path(ic.LOG_FILE).read_text().splitlines()
    assert len(lines) == 4 and json.loads(lines[1])["source"] == "mic"
    ic.clear_view()
    assert ic.recent() == [] and len(Path(ic.LOG_FILE).read_text().splitlines()) == 4   # file kept


def test_log_reload_after_restart(monkeypatch):
    ic.record("app", "a", "b")
    ic.record("app", "c", "d")
    monkeypatch.setattr(ic, "_log", ic.deque(maxlen=300))
    monkeypatch.setattr(ic, "_loaded_log", False)
    monkeypatch.setattr(ic, "_seq", 0)
    assert len(ic.recent()) == 2
    assert ic.record("app", "e", "f")["id"] == 3
