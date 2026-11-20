import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.lab_map_service import lab_map  # noqa: E402


def test_live_prefers_localizer():
    r = lab_map.combine_live({"route": "lab_tour", "state": "running"},
                             {"map": [1.5, -2.0, 0.3], "quality": "good", "age_s": 0.1})
    assert r["pose"]["source"] == "lidar_localizer"
    assert r["pose"]["x"] == 1.5 and r["pose"]["route"] == "lab_tour"


def test_live_without_guide_but_with_localizer():
    r = lab_map.combine_live(None, {"map": [0, 0, 0], "quality": "weak"})
    assert r["pose"]["quality"] == "weak"


def test_live_lost_localizer_and_no_guide():
    assert lab_map.combine_live(None, {"map": [0, 0, 0], "quality": "lost"})["pose"] is None
    assert lab_map.combine_live(None, None)["pose"] is None
