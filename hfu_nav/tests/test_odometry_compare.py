import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import odometry_compare as oc

def track(c, drift_from=None, rate=0.05):
    for i in range(600):
        t = 100 + i * 0.1
        x, y = i * 0.05, 0.0                       # 30 m straight
        c.add_recorded(t, x, y, 0.0)
        d = 0.0 if drift_from is None or x < drift_from else (x - drift_from) * rate * 10
        c.add_live(t + 0.01, x + d, y, 0.0)

def test_same_paths():
    c = oc.Compare(); track(c)
    s = c.summary()
    assert s["verdict"] == "SAME AS MAPPING DAY" and s["difference_xy_max_m"] < 0.01
    assert 29 < s["route_length_m"] < 31

def test_divergence_found_with_distance():
    c = oc.Compare(); track(c, drift_from=10.0)
    s = c.summary()
    assert s["verdict"] == "FAST-LIO DIVERGES FROM MAPPING DAY"
    assert 10 <= s["first_diverges_at_m"] <= 12
    assert s["difference_at_distance"]["5m"]["xy"] == 0.0

def test_no_data():
    assert oc.Compare().summary()["verdict"] == "NO DATA"
