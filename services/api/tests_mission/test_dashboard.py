import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import host_stats


def build_alerts(*a):
    import importlib, types
    # dashboard.py imports the websocket manager (FastAPI) - load only the function
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "dashboard.py").read_text()
    start = src.index("def build_alerts")
    end = src.index("def _today")
    ns: dict = {}
    exec(src[start:end], ns)
    return ns["build_alerts"](*a)


def test_alerts():
    tel = {"battery": {"soc": 18}, "body": {"motors": [{"joint": "L knee", "temp_c": 78},
                                                       {"joint": "R knee", "temp_c": 62}],
                                            "imu_roll_deg": 2, "imu_pitch_deg": -1},
           "thresholds": {"motor_warn_c": 60, "motor_hot_c": 75}}
    services = [{"name": "Camera bridge", "required": True, "ok": False, "detail": "no frames"},
                {"name": "Vision", "required": False, "ok": False, "detail": "x"}]
    a = build_alerts({"estop": False}, services, tel, {"wifi": {"signal_dbm": -80}, "disk": {"used_percent": 50}})
    texts = " | ".join(x["text"] for x in a)
    assert a[0]["level"] == "critical"
    assert "Battery 18 %" in texts and "L knee 78" in texts and "(+1 more)" in texts
    assert "Camera bridge is down" in texts and "Vision" not in texts and "Weak Wi-Fi" in texts


def test_host_snapshot_runs_anywhere():
    s = host_stats.snapshot()
    s2 = host_stats.snapshot()
    assert "memory" in s and "disk" in s and s2["cpu_percent"] is None or s2["cpu_percent"] >= 0
