import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import feedback_service as fb


def test_sus_score_standard():
    assert fb.sus_score([5, 1] * 5) == 100.0
    assert fb.sus_score([1, 5] * 5) == 0.0
    assert fb.sus_score([3] * 10) == 50.0
    assert fb.sus_score([4, 2, 4, 2, 4, 2, 4, 2, 4, 2]) == 75.0
    assert fb.sus_score([3] * 9) is None


def test_submit_stats_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "FEEDBACK_FILE", str(tmp_path / "f.jsonl"))
    fb._last_submit.clear()
    fb.submit({"rating": 5, "recommend": "yes", "context": "tour:lab_tour", "lang": "de",
               "sus": [4, 2, 4, 2, 4, 2, 4, 2, 4, 2], "comment": "Super!"})
    fb.submit({"rating": 3, "recommend": "maybe"})
    with pytest.raises(ValueError):
        fb.submit({"rating": 9})
    with pytest.raises(ValueError):
        fb.submit({})
    s = fb.stats(fb.load())
    assert s["count"] == 2 and s["avg_rating"] == 4.0 and s["sus_mean"] == 75.0
    assert s["recommend_yes_pct"] == 50
    csv = fb.to_csv(fb.load())
    assert "sus_10" in csv.splitlines()[0] and "Super!" in csv
