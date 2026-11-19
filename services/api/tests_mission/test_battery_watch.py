import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.battery_watch import BatteryWatch


def kinds(actions):
    return [a for a in actions]


def test_levels_speech_and_reminders():
    t = [0.0]
    w = BatteryWatch(clock=lambda: t[0])
    assert w.update(80, False, False) == [("broadcast", "ok")]
    assert w.update(49, False, False) == [("broadcast", "low"), ("speak", "low")]
    t[0] = 60
    assert w.update(48, False, False) == []                     # no repeat right away
    assert w.update(51, False, False) == []                     # hysteresis: still low
    t[0] = 60 + 20 * 60
    assert w.update(47, False, False) == [("speak", "low")]     # 20 min reminder
    assert w.update(19, False, False) == [("broadcast", "critical"), ("speak", "critical")]
    t[0] += 60
    assert w.update(18, False, False) == []
    t[0] += 5 * 60
    assert w.update(17, False, False) == [("speak", "critical")]
    assert w.update(60, True, False) == [("broadcast", "ok")]   # charged


def test_low_waits_for_tour_critical_does_not():
    t = [0.0]
    w = BatteryWatch(clock=lambda: t[0])
    w.update(70, False, False)
    assert w.update(45, False, True) == [("broadcast", "low")]   # tour running -> wait
    t[0] = 30
    assert w.update(45, False, True) == []
    assert w.update(45, False, False) == [("speak", "low")]      # tour finished -> speak now
    assert w.update(15, False, True) == [("broadcast", "critical"), ("speak", "critical")]


def test_silent_while_charging_and_texts():
    w = BatteryWatch(clock=lambda: 0.0)
    w.update(70, False, False)
    assert w.update(30, True, False) == [("broadcast", "low")]
    texts = w.texts("critical")
    assert texts[0][1] == "en" and "30 percent" in texts[0][0] and "Prozent" in texts[1][0]
