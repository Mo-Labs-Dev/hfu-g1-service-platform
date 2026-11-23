import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import talk_cards_service as tc


@pytest.fixture(autouse=True)
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "CARDS_FILE", str(tmp_path / "cards.json"))
    ev = []
    monkeypatch.setattr(tc, "broadcaster", ev.append)
    return ev


def test_library_defaults():
    d = tc.load()
    assert len(d["cards"]) == len(tc.LIBRARY) >= 40
    assert len({c["id"] for c in tc.LIBRARY}) == len(tc.LIBRARY)       # unique ids
    on = tc.app_cards()["cards"]
    assert 4 <= len(on) <= tc.MAX_IN_APP and on[0]["en"] == "Who are you?"


def test_save_order_custom_and_push(files):
    cards = tc.load()["cards"]
    for c in cards:
        c["enabled"] = c["id"] in ("joke", "who")
    custom = {"en": "  When  is the open house? ", "de": "", "category": "", "enabled": True,
              "answer_en": "Open house is on Friday at two pm."}
    out = tc.save([custom] + cards[::-1])
    app = tc.app_cards()
    assert [c["en"] for c in app["cards"]] == ["When is the open house?", "Tell me a joke", "Who are you?"]
    assert app["cards"][0]["de"] == "When is the open house?"            # missing German -> English
    assert out["cards"][0]["category"] == "My cards" and not out["cards"][0]["builtin"]
    assert files[-1]["type"] == "talk_cards_changed" and app["version"] == 1


def test_validation():
    with pytest.raises(ValueError):
        tc.save([{"en": ""}])
    with pytest.raises(ValueError):
        tc.save([{"en": "x" * (tc.TEXT_MAX + 1)}])
    with pytest.raises(ValueError):
        tc.save([{"en": f"q{i}", "enabled": True} for i in range(tc.MAX_IN_APP + 1)])


def test_fixed_answer_matching():
    assert tc.fixed_answer("Who are you?")[0].startswith("I'm G1")
    assert tc.fixed_answer("who are you", "de")[1] == "de"                 # app set to German
    assert tc.fixed_answer("Wer bist du?")[1] == "de"
    assert tc.fixed_answer("What can you do?") is None                    # no fixed answer -> AI
    assert tc.fixed_answer("What is your name?") is None                  # card is switched off
    assert tc.fixed_answer("Who are you and what do you do?") is None     # only exact card text


def test_deleted_builtin_comes_back_hidden():
    cards = [c for c in tc.load()["cards"] if c["id"] != "who"]
    tc.save(cards)
    who = [c for c in tc.load()["cards"] if c["id"] == "who"]
    assert len(who) == 1 and who[0]["enabled"] is False
