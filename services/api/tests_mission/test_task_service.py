import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.task_service import TaskRunner, parse  # noqa: E402


def test_parse_en_de():
    assert parse("Can you show me target A?") == {"action": "show", "target": "target_a"}
    assert parse("pick the box A") == {"action": "pick", "target": "target_a"}
    assert parse("Please pick up the object") == {"action": "pick", "target": "object"}
    assert parse("Zeig mir Ziel B") == {"action": "show", "target": "target_b"}
    assert parse("Nimm die Tasse") == {"action": "pick", "target": "object"}
    assert parse("Wo ist das Objekt?") == {"action": "show", "target": "object"}
    assert parse("What is the weather today?") is None
    assert parse("Guide me to the coffee machine") is None


class Fake:
    def __init__(self, visible_here=True, visible_at_table=True):
        self.here, self.table, self.walked = visible_here, visible_at_table, False
        self.said, self.pointed, self.t = [], [], 0.0
        self.guide_polls = 0

    def clock(self):
        return self.t

    def sleep(self, dt):
        self.t += dt

    def scene(self):
        vis = self.table if self.walked else self.here
        return {"tags": [{"name": "target_a", "reachable": True, "side": "right"}] if vis else []}

    def point(self, key, lang):
        self.pointed.append(key)
        return True, "started"

    def pick_status(self):
        return {"state": "done", "target": self.pointed[-1] if self.pointed else None}

    def goto(self, name, lang):
        self.walked = True
        return True, "started"

    def guide_status(self):
        self.guide_polls += 1
        return {"state": "done" if self.guide_polls > 3 else "guiding"}

    def say(self, text, lang):
        self.said.append(text)


def make(f, dests):
    return TaskRunner(f.scene, f.point, f.pick_status, f.goto, f.guide_status, lambda: dests, f.say,
                      clock=f.clock, sleep=f.sleep)


def test_in_view_points_directly():
    f = Fake()
    r = make(f, [])
    out = r.handle("show me target A", "en")
    assert out["handled"] and "show you target A" in out["reply"]
    r.thread.join(5)
    st = r.snapshot()
    assert st["result"] == "done" and f.pointed == ["target_a"] and not f.walked


def test_not_in_view_walks_to_the_table_first():
    f = Fake(visible_here=False)
    r = make(f, [{"name": "work_table", "title_en": "Work table", "title_de": "Werktisch"}])
    out = r.handle("pick the box A", "en")
    assert "gripper" in out["reply"]
    r.thread.join(5)
    st = r.snapshot()
    assert f.walked and st["result"] == "done"
    assert any("walking to" in s["text"] for s in st["steps"])


def test_not_in_view_and_no_table():
    f = Fake(visible_here=False)
    r = make(f, [{"name": "coffee", "title_en": "Coffee machine"}])
    r.handle("zeig mir ziel A", "de")
    r.thread.join(5)
    assert r.snapshot()["result"] == "not_seen" and f.pointed == []


def test_non_task_is_not_handled():
    r = make(Fake(), [])
    assert r.handle("tell me a joke", "en") == {"handled": False}
