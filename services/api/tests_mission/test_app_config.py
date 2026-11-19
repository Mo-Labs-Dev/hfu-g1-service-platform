import json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import app_config_service as ac


def test_defaults_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    c = ac.load()
    assert c["tiles"]["robot_show"] and not c["announcement"]["active"]
    c2 = ac.save({"announcement": {"active": True, "text_en": "Lab closes at 17:00", "level": "warning"},
                  "tiles": {"robot_show": False, "bogus": False}})
    assert c2["version"] == c["version"] + 1 and c2["announcement"]["level"] == "warning"
    assert c2["tiles"]["robot_show"] is False and "bogus" not in c2["tiles"]
    assert ac.load()["announcement"]["text_en"] == "Lab closes at 17:00"
    with pytest.raises(ValueError):
        ac.save({"tiles": {k: False for k in ac.TILES}})
