import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import destinations_service as d  # noqa: E402


def test_upsert_list_delete(tmp_path):
    f = str(tmp_path / "dest.json")
    a = d.upsert({"title_en": "Coffee machine", "x": 1.234567, "y": -2, "yaw": 0.5}, f)
    assert a["name"] == "coffee_machine" and a["x"] == 1.235 and a["title_de"] == "Coffee machine"
    d.upsert({"title_en": "Yaskawa robot", "title_de": "Yaskawa-Roboter", "x": 5, "y": 6}, f)
    d.upsert({"name": "coffee_machine", "title_en": "Coffee machine", "x": 2, "y": 2}, f)   # update
    items = d.list_all(f)
    assert [i["name"] for i in items] == ["coffee_machine", "yaskawa_robot"]
    assert d.get("coffee_machine", f)["x"] == 2 and d.get("coffee_machine", f)["created"] == a["created"]
    d.delete("yaskawa_robot", f)
    with pytest.raises(KeyError):
        d.delete("yaskawa_robot", f)
    with pytest.raises(ValueError):
        d.upsert({"title_en": "", "x": 1, "y": 1}, f)
    with pytest.raises(ValueError):
        d.upsert({"title_en": "x", "y": 1}, f)
