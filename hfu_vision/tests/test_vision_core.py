import math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision_core import FindParams, VisionRunner, bearing, find_target


class FakeWorld:
    """Robot that turns; a bottle stands at a fixed bearing; camera sees +-34.5 deg."""
    def __init__(self, bottle_deg=100.0, estop=False):
        self.t, self.yaw, self.w = 0.0, 0.0, 0.0
        self.bottle = math.radians(bottle_deg)
        self.said, self.gestures, self.events = [], [], []
        self.estop = estop
        self.stop_count = 0
        self.pictures = 0
    # clock
    def clock(self): return self.t
    def sleep(self, dt):
        self.t += dt
        self.yaw += self.w * dt
    # motion (teleop)
    def status(self): return {"fsm_id": 500, "estop": self.estop, "teleop_active": False,
                              "gesture": None, "limits": {"max_yaw": 0.8}}
    def begin(self): self.events.append("begin")
    def end(self): self.events.append("end"); self.w = 0.0
    def send(self, x, yaw): self.w = yaw * 0.8
    def gesture(self, name): self.gestures.append(name)
    def stopped_by_operator(self): return self.stop_count > 0
    # camera + detector
    def snapshot(self):
        self.pictures += 1
        return b"jpeg"
    def detect(self, jpeg):
        rel = math.degrees(math.atan2(math.sin(self.bottle - self.yaw), math.cos(self.bottle - self.yaw)))
        dets = []
        if abs(rel) < 34.5:
            cx = (0.5 - rel / 69.0) * 1920
            dets.append({"label": "bottle", "confidence": 0.8,
                         "bbox": {"x1": cx - 40, "y1": 300, "x2": cx + 40, "y2": 500}})
        dets.append({"label": "person", "confidence": 0.9, "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 300}})
        return {"image": {"width": 1920, "height": 1080}, "detections": dets}
    # vlm + voice
    def ask(self, jpeg, prompt): return "I see a workbench with a laptop."
    def say(self, text, lang): self.said.append(text)


def runner(w):
    return VisionRunner(camera=w, detector=w, vlm=w, motion=w, voice=w, params=FindParams(),
                        clock=w.clock, sleep=w.sleep)


def test_find_target_words():
    assert find_target("G1, can you find the bottle?") == "bottle"
    assert find_target("Wo ist meine Tasse?") == "cup"
    assert find_target("find a coffee cup") == "cup"
    assert find_target("Finde den Rucksack") == "backpack"
    assert find_target("find the unicorn") is None


def test_bearing_sign():
    det = {"bbox": {"x1": 0, "x2": 200}}
    assert bearing(det, 1920, 69) > 0          # object on the left -> turn left (+)


def test_finds_bottle_turns_to_it_and_waves():
    w = FakeWorld(bottle_deg=100)
    g = runner(w)
    assert g.find("find the bottle", "en") == "found"
    err = math.degrees(math.atan2(math.sin(w.bottle - w.yaw), math.cos(w.bottle - w.yaw)))
    assert abs(err) < 8, err                    # facing the bottle
    assert w.gestures == ["high_wave"] and w.events == ["begin", "end"]
    assert any("found the bottle" in s for s in w.said)


def test_not_found_after_full_circle():
    w = FakeWorld()
    w.detect = lambda jpeg: {"image": {"width": 1920}, "detections": []}
    g = runner(w)
    assert g.find("bottle", "de") == "not_found"
    assert abs(w.yaw) > math.radians(300)       # looked all around
    assert any("nicht finden" in s for s in w.said) and w.events[-1] == "end"


def test_refuses_with_estop_and_unknown_object():
    w = FakeWorld(estop=True)
    g = runner(w)
    assert g.find("bottle") == "error" and "begin" not in w.events
    w2 = FakeWorld()
    assert runner(w2).find("find the unicorn") == "unknown"


def test_operator_stop_cancels():
    w = FakeWorld()
    w.detect = lambda jpeg: {"image": {"width": 1920}, "detections": []}
    orig = w.sleep
    def sleep(dt):
        orig(dt)
        if w.t > 5: w.stop_count = 1
    w.sleep = sleep
    g = runner(w)
    assert g.find("bottle") == "cancelled" and w.events[-1] == "end"


def test_describe_speaks_answer():
    w = FakeWorld()
    g = runner(w)
    assert "workbench" in g.describe("", "en")
    assert w.said == ["I see a workbench with a laptop."]
