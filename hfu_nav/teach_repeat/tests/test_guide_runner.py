import math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guide_runner import GuideRunner
from route_core import FollowParams, wrap
from test_route_core import l_route

class World:
    """Fake clock + simulated G1 + fake teleop server/sensors/voice."""
    def __init__(self, x=0.0, y=0.0, yaw=0.0):
        self.t = 1000.0
        self.x, self.y, self.z, self.yaw = x, y, 0.0, yaw
        self.v = self.w = 0.0
        self.fsm, self.estop, self.teleop_active = 500, False, False
        self.stop_count = 0
        self.obstacle = None            # (t_from, t_to)
        self.jump_at = None
        self.said = []
        self.events = []
        self.p = FollowParams()
    # clock
    def clock(self): return self.t
    def sleep(self, dt):
        self.t += dt
        self.yaw = wrap(self.yaw + self.w * dt)
        self.x += self.v * math.cos(self.yaw) * dt
        self.y += self.v * math.sin(self.yaw) * dt
        if self.jump_at and self.t >= self.jump_at:
            self.x += 5.0; self.jump_at = None
    # motion
    def status(self): return {"fsm_id": self.fsm, "estop": self.estop,
                              "teleop_active": self.teleop_active, "stop_count": self.stop_count}
    def begin(self): self.events.append("begin")
    def end(self): self.events.append("end"); self.v = self.w = 0.0
    def send(self, x, yaw):
        self.v = x * self.p.max_forward_mps; self.w = yaw * self.p.max_yaw_rate
    def stopped_by_operator(self): return self.stop_count > 0
    # sensors
    def pose(self): return (self.t, self.x, self.y, self.z, self.yaw)
    def points(self):
        if self.obstacle and self.obstacle[0] <= self.t < self.obstacle[1]:
            c, s = math.cos(self.yaw), math.sin(self.yaw)
            return np.array([[self.x + 0.8 * c - k * 0.05 * s, self.y + 0.8 * s + k * 0.05 * c, -0.6]
                             for k in range(-5, 6)])
        return np.zeros((0, 3))
    # voice
    def say(self, text, lang): self.said.append(text)

def runner(w):
    return GuideRunner(motion=w, sensors=w, voice=w, params=w.p, clock=w.clock, sleep=w.sleep)

def test_full_tour_out_and_back():
    w = World(); g = runner(w)
    assert g.run(l_route(), "en", return_home=True, wait_s=5) == "done"
    states = [h[1] for h in g.status.history]
    for s in ("starting", "guiding", "arrived", "returning", "done"):
        assert s in states
    assert math.hypot(w.x, w.y) < 0.35                      # back home
    assert any("take you to the coffee machine" in s for s in w.said)
    assert any(s.startswith("Here is the coffee machine") for s in w.said)
    assert w.events == ["begin", "end"]

def test_german_announcements():
    w = World(); g = runner(w)
    r = l_route(); r.title_de = "Kaffeemaschine"
    g.run(r, "de", return_home=False)
    assert any("Kaffeemaschine" in s for s in w.said)

def test_operator_stop_aborts_and_releases():
    w = World(); g = runner(w)
    orig = w.sleep
    def sleep(dt):
        orig(dt)
        if w.t > 1010: w.stop_count = 1                     # STOP pressed in the app
    g.sleep = sleep
    assert g.run(l_route(), "en") == "aborted"
    assert "STOP" in g.status.message and w.events[-1] == "end"

def test_preflight_refusals():
    for attr, val in (("fsm", 4), ("teleop_active", True), ("estop", True)):
        w = World(); setattr(w, attr, val)
        g = runner(w)
        assert g.run(l_route(), "en") == "aborted"
        assert "begin" not in w.events                      # never took control

def test_not_on_home_spot():
    w = World(x=3.0, y=0.0); g = runner(w)
    assert g.run(l_route(), "en") == "aborted"
    assert "home spot" in g.status.message

def test_waits_for_obstacle_and_asks_to_pass():
    w = World(); w.obstacle = (1005.0, 1017.0)
    g = runner(w)
    assert g.run(l_route(), "en", return_home=False) == "done"
    assert "blocked" in [h[1] for h in g.status.history]
    assert any("let me pass" in s for s in w.said)

def test_fastlio_jump_aborts():
    w = World(); w.jump_at = 1010.0
    g = runner(w)
    assert g.run(l_route(), "en") == "aborted"
    assert "jumped" in g.status.message or "away from the taught route" in g.status.message
    assert w.v == 0.0

def test_cancel():
    w = World(); g = runner(w)
    orig = w.sleep
    def sleep(dt):
        orig(dt)
        if w.t > 1008: g.cancel()
    g.sleep = sleep
    assert g.run(l_route(), "en") == "cancelled"
