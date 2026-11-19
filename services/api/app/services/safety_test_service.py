"""
Safety test mode: measures how fast G1 really stops, from G1's own measured
speed (rt/odommodestate via the telemetry service, 50 Hz).

  stop      STOP button while G1 walks (joystick or guide)
  estop     software E-STOP while G1 walks (reset afterwards in the app)
  obstacle  armed during a guide run: someone steps into the path -> time from
            "blocked" detection to standstill

Result per test: reaction time (trigger -> speed < 0.05 m/s for 0.3 s), stopping
distance (integrated speed), speed at trigger. Saved to data/safety_tests.jsonl.
All timestamps use CLOCK_MONOTONIC, which is shared by all processes / containers
on the Jetson.
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time

from app.services import robot_hub
from app.services.lab_map_service import _DATA

RESULTS_FILE = os.path.expanduser(os.getenv("G1_SAFETY_FILE", os.path.join(_DATA, "safety_tests.jsonl")))
STOP_SPEED = 0.05       # m/s = standing
HOLD_S = 0.3            # must stay below for this long
MIN_TRIGGER_SPEED = 0.08
KINDS = {"stop": "STOP button", "estop": "Software E-STOP", "obstacle": "Obstacle in the path (guide)"}


def analyse(samples: list, t0: float) -> dict:
    """samples: [(t, speed, yaw_rate)] around the trigger time t0."""
    before = [s for s in samples if t0 - 0.4 <= s[0] <= t0]
    after = [s for s in samples if s[0] >= t0]
    v0 = max((s[1] for s in before), default=after[0][1] if after else None)
    if not after or v0 is None:
        return {"ok": False, "reason": "no speed data from G1 (telemetry running?)"}
    stop_t = None
    for i, (t, v, _) in enumerate(after):
        if v < STOP_SPEED:
            hold = [s for s in after[i:] if s[0] <= t + HOLD_S]
            if hold and all(s[1] < STOP_SPEED for s in hold) and after[-1][0] >= t + HOLD_S:
                stop_t = t
                break
    if stop_t is None:
        return {"ok": False, "reason": "G1 did not come to a standstill within the window", "speed_at_trigger": v0}
    dist, prev = 0.0, None
    for t, v, _ in after:
        if t > stop_t:
            break
        if prev is not None:
            dist += (t - prev[0]) * (v + prev[1]) / 2.0
        prev = (t, v)
    reaction = stop_t - t0
    return {"ok": True, "reaction_s": round(reaction, 3), "stop_distance_m": round(dist, 3),
            "speed_at_trigger": round(v0, 3),
            "decel_mps2": round(v0 / reaction, 2) if reaction > 0 else None}


class SafetyTests:
    def __init__(self):
        self._lock = threading.Lock()
        self.running: dict | None = None
        self.last: dict | None = None

    def status(self) -> dict:
        return {"running": self.running, "last": self.last}

    def start(self, kind: str, note: str) -> dict:
        if kind not in KINDS:
            raise KeyError(kind)
        with self._lock:
            if self.running:
                raise RuntimeError("A safety test is already running.")
            if kind in ("stop", "estop"):
                speed = self._speed_now()
                if speed is None:
                    raise RuntimeError("No speed data from G1 – is the telemetry service running?")
                if speed < MIN_TRIGGER_SPEED:
                    raise RuntimeError(f"G1 is not walking ({speed:.2f} m/s). Let G1 walk first (joystick or guide).")
            self.running = {"kind": kind, "label": KINDS[kind], "state": "armed" if kind == "obstacle" else "running",
                            "since": time.time()}
        threading.Thread(target=self._run, args=(kind, note), daemon=True).start()
        return self.status()

    def cancel(self):
        if self.running:
            self.running["cancel"] = True

    def _speed_now(self):
        try:
            d = robot_hub.telemetry_speed(time.monotonic() - 1.0)
            return d["samples"][-1][1] if d.get("samples") else None
        except Exception:
            return None

    def _run(self, kind: str, note: str):
        result = {"kind": kind, "label": KINDS[kind], "note": note[:200],
                  "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            if kind == "obstacle":
                t0 = None
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline and not (self.running or {}).get("cancel"):
                    try:
                        st = robot_hub.guide_status()
                    except Exception:
                        st = {}
                    if st.get("state") == "blocked":
                        t0 = time.monotonic()
                        result["guide_message"] = st.get("message", "")
                        break
                    time.sleep(0.05)
                if t0 is None:
                    result.update({"ok": False, "reason": "cancelled / no obstacle detected within 3 min"})
                    return
                self.running["state"] = "measuring"
            else:
                t0 = time.monotonic()
                (robot_hub.stop if kind == "stop" else robot_hub.estop)()
            time.sleep(4.0)
            samples = robot_hub.telemetry_speed(t0 - 1.0).get("samples", [])
            result.update(analyse(samples, t0))
            result["samples"] = [[round(s[0] - t0, 2), s[1]] for s in samples if s[0] <= t0 + 4][::2]
        except Exception as exc:
            result.update({"ok": False, "reason": str(exc)})
        finally:
            self.last = result
            self.running = None
            if not result.get("reason", "").startswith("cancelled"):
                self._save(result)

    def _save(self, result: dict):
        os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
        with open(RESULTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")


def load() -> list[dict]:
    out = []
    try:
        with open(RESULTS_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def stats(items: list[dict]) -> dict:
    out = {}
    for kind, label in KINDS.items():
        ok = [i for i in items if i.get("kind") == kind and i.get("ok")]
        rt = [i["reaction_s"] for i in ok]
        dist = [i["stop_distance_m"] for i in ok]
        out[kind] = {
            "label": label, "n": len(ok),
            "failed": sum(1 for i in items if i.get("kind") == kind and not i.get("ok")),
            "reaction_mean_s": round(statistics.mean(rt), 3) if rt else None,
            "reaction_sd_s": round(statistics.stdev(rt), 3) if len(rt) > 1 else None,
            "reaction_max_s": round(max(rt), 3) if rt else None,
            "distance_mean_m": round(statistics.mean(dist), 3) if dist else None,
            "distance_max_m": round(max(dist), 3) if dist else None,
        }
    return out


safety_tests = SafetyTests()
