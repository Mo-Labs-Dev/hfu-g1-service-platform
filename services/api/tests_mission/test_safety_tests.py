import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import safety_test_service as st


def ramp(t0=10.0, v=0.3, decel=1.0):
    """Walking at v, trigger at t0, 0.15 s latency, then constant deceleration."""
    s, t = [], t0 - 1.0
    while t < t0 + 4:
        if t < t0 + 0.15:
            speed = v
        else:
            speed = max(0.0, v - decel * (t - t0 - 0.15))
        s.append((round(t, 3), round(speed, 4), 0.0))
        t += 0.02
    return s


def test_analyse_reaction_and_distance():
    r = st.analyse(ramp(), 10.0)
    assert r["ok"]
    # stops when v < 0.05: 0.15 + 0.25 = 0.40 s
    assert abs(r["reaction_s"] - 0.40) < 0.03
    # distance: 0.3*0.15 + area of the ramp until 0.05 m/s (~0.04375) = ~0.089 m
    assert abs(r["stop_distance_m"] - 0.089) < 0.01
    assert r["speed_at_trigger"] == 0.3


def test_analyse_never_stops():
    s = [(t / 50, 0.3, 0.0) for t in range(0, 300)]
    assert st.analyse(s, 1.0)["ok"] is False


def test_stats():
    items = [{"kind": "stop", "ok": True, "reaction_s": 0.4, "stop_distance_m": 0.08},
             {"kind": "stop", "ok": True, "reaction_s": 0.6, "stop_distance_m": 0.12},
             {"kind": "stop", "ok": False, "reason": "x"}]
    s = st.stats(items)["stop"]
    assert s["n"] == 2 and s["failed"] == 1 and s["reaction_mean_s"] == 0.5 and s["reaction_max_s"] == 0.6
