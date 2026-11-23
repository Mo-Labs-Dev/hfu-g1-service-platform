"""
Spoken tasks -> autonomous behaviour (task-level autonomy).

    "Show me target A" / "Zeig mir Ziel B" / "Pick up the box" / "Nimm das Objekt"

1. understand:  verb (show / pick) + thing (object, target A, target B)
2. plan:        is the thing in view and in reach?  -> act here
                not in view, but a work-table destination exists -> walk there first (autonomous
                walking), then look again
3. act:         "point at it" arm demo (robot service :8005). "pick" is honest until the gripper is
                mounted: G1 says so and shows the thing instead.

Every step is visible in /api/task/status and logged; the robot keeps all its own safety checks.
"""
from __future__ import annotations

import re
import threading
import time

TARGET_WORDS = [
    # (pattern, key) - most specific first
    (r"\b(target|ziel|box|kiste|place|platz|spot)\s*-?\s*a\b", "target_a"),
    (r"\b(target|ziel|box|kiste|place|platz|spot)\s*-?\s*b\b", "target_b"),
    (r"\b(object|objekt|gegenstand|box|kiste|cup|tasse|basket|korb|thing|ding)\b", "object"),
]
PICK_WORDS = r"\b(pick|grab|take|get|bring|lift|nimm|nehmen|hol|holen|greif|greifen|heb|heben|bring)\w*"
SHOW_WORDS = r"\b(show|point|where|look|find|zeig|zeige|zeigen|wo|such|finde|schau)\w*"
TITLES = {"object": ("the object", "das Objekt"), "target_a": ("target A", "Ziel A"),
          "target_b": ("target B", "Ziel B")}
STATION_HINTS = ("table", "tisch", "pick", "station", "werkbank", "bench")


def parse(text: str) -> dict | None:
    t = " " + re.sub(r"[^a-zäöüß0-9 ]+", " ", (text or "").lower()) + " "
    target = next((key for pat, key in TARGET_WORDS if re.search(pat, t)), None)
    if target is None:
        return None
    if re.search(PICK_WORDS, t):
        action = "pick"
    elif re.search(SHOW_WORDS, t):
        action = "show"
    else:
        return None
    return {"action": action, "target": target}


class TaskRunner:
    """All robot parts injected (unit tested with fakes)."""

    def __init__(self, scene, point, pick_status, goto, guide_status, destinations, say,
                 clock=time.monotonic, sleep=time.sleep):
        self.scene, self.point, self.pick_status = scene, point, pick_status
        self.goto, self.guide_status, self.destinations, self.say = goto, guide_status, destinations, say
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self.status = {"state": "idle", "steps": [], "task": None, "result": None}
        self.thread: threading.Thread | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {**self.status, "steps": list(self.status["steps"])}

    def _step(self, text: str) -> None:
        with self._lock:
            self.status["steps"].append({"t": round(self.clock(), 1), "text": text})

    def _finish(self, result: str, text: str) -> str:
        self._step(text)
        with self._lock:
            self.status.update(state="done" if result == "done" else "failed", result=result)
        return result

    def busy(self) -> bool:
        return self.snapshot()["state"] == "running"

    def station(self) -> dict | None:
        for d in self.destinations():
            name = (d.get("name", "") + " " + d.get("title_en", "") + " " + d.get("title_de", "")).lower()
            if any(h in name for h in STATION_HINTS):
                return d
        return None

    # ---------------------------------------------------------------- entry
    def handle(self, text: str, lang: str = "en") -> dict:
        task = parse(text)
        de = lang == "de"
        if task is None:
            return {"handled": False}
        title = TITLES[task["target"]][1 if de else 0]
        if self.busy():
            return {"handled": True, "reply": "Ich bin noch mit der letzten Aufgabe beschäftigt." if de
                    else "I am still busy with the last task."}
        with self._lock:
            self.status = {"state": "running", "steps": [], "task": task, "result": None, "lang": lang}
        if task["action"] == "pick":
            reply = (f"Ich kann noch nicht greifen - mein Greifer kommt am Donnerstag. Ich zeige Ihnen {title}."
                     if de else f"I can't grab things yet - my gripper arrives on Thursday. I will show you {title}.")
        else:
            reply = f"Gerne, ich zeige Ihnen {title}." if de else f"Sure, I will show you {title}."
        self.thread = threading.Thread(target=self._run, args=(task, lang), daemon=True)
        self.thread.start()
        return {"handled": True, "reply": reply, "task": task}

    # ---------------------------------------------------------------- run
    def _visible(self, key) -> dict | None:
        try:
            return next((t for t in self.scene().get("tags", []) if t.get("name") == key), None)
        except Exception:
            return None

    def _run(self, task: dict, lang: str) -> str:
        key = task["target"]
        de = lang == "de"
        self._step(f"Understood: {task['action']} {TITLES[key][0]}")
        if task["action"] == "pick":
            try:
                self.say("Ich kann noch nicht greifen. Ich zeige es Ihnen." if de
                         else "I can't grab yet. I will show it to you instead.", lang)
            except Exception:
                pass
        tag = self._visible(key)
        if tag is None:
            st = self.station()
            if st is None:
                return self._finish("not_seen", f"{TITLES[key][0]} is not in view and no work table destination exists")
            self._step(f"Not in view - walking to '{st.get('title_en') or st['name']}' (autonomous walking)")
            ok, msg = self.goto(st["name"], lang)
            if not ok:
                return self._finish("walk_failed", f"Could not start walking: {msg}")
            t0 = self.clock()
            while True:
                self.sleep(1.0)
                g = self.guide_status() or {}
                if g.get("state") == "done":
                    break
                if g.get("state") in ("aborted", "cancelled", "failed") or self.clock() - t0 > 240:
                    return self._finish("walk_failed", f"Walk ended: {g.get('state')} {g.get('message', '')}")
            self._step("Arrived at the table - looking again")
            self.sleep(1.5)
            tag = self._visible(key)
            if tag is None:
                return self._finish("not_seen", f"{TITLES[key][0]} not seen at the table")
        if not tag.get("reachable"):
            return self._finish("not_reachable", f"{TITLES[key][0]} is in view but too far for the arm")
        self._step(f"Seen {TITLES[key][0]} - showing it with the {tag.get('side')} arm")
        ok, msg = self.point(key, lang)
        if not ok:
            return self._finish("refused", f"Arm demo refused: {msg}")
        t0 = self.clock()
        while True:
            self.sleep(0.5)
            p = self.pick_status() or {}
            if p.get("state") in ("done", "failed", "stopped", "refused") and p.get("target") == key:
                break
            if self.clock() - t0 > 60:
                return self._finish("timeout", "Arm demo did not finish")
        if p.get("state") == "done":
            return self._finish("done", f"Done: showed {TITLES[key][0]}")
        return self._finish(p.get("state", "failed"), f"Arm demo: {p.get('message', p.get('state'))}")
