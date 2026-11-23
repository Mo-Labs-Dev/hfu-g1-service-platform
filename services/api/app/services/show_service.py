"""
Show mode - demo scripts built from blocks in G1 Studio and run with one button.

Blocks (steps):
  say      G1 says a sentence (EN/DE), arms gesture if switched on
  ask      G1 answers a question like a visitor asked it (AI or fixed speaking-card answer)
  gesture  wave / clap / heart / ...  (teleop visitor gesture, robot standing)
  walk     walk autonomously to a saved Lab Map destination (map localizer + planner)
  point    point at the object / target A / target B on the table (camera-guided arm)
  wait     pause N seconds
  pause    wait until the operator presses "Continue" (e.g. "let visitors ask questions")

Run modes: "auto" (step after step) or "step" (operator presses Continue after every step).
Safety: every motion step runs the same preflight as Robot Show / guide (E-stop, walking mode,
no joystick, nothing else moving); Stop cancels guide + arm at once; any failed step ends the
show. The remote stays in the operator's hand - the show never replaces it.

Shows: data/shows.json. Every run: data/show_runs.jsonl (Evaluation).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
SHOWS_FILE = os.path.expanduser(os.getenv("G1_SHOWS_FILE", os.path.join(_DATA, "shows.json")))
RUNS_FILE = os.path.expanduser(os.getenv("G1_SHOW_RUNS_FILE", os.path.join(_DATA, "show_runs.jsonl")))

GESTURES = ("high_wave", "face_wave", "clap", "heart", "two_hand_kiss")
TARGETS = ("object", "target_a", "target_b")
TYPES = ("say", "ask", "gesture", "walk", "point", "wait", "pause")
MOTION = ("gesture", "walk", "point")
MAX_SHOWS, MAX_STEPS, TEXT_MAX = 50, 40, 400


# ---------------------------------------------------------------- storage
def _txt(v, n=TEXT_MAX) -> str:
    return " ".join(str(v or "").split())[:n]


def clean_step(s: dict) -> dict:
    t = s.get("type")
    if t not in TYPES:
        raise ValueError(f"Unknown step type '{t}'")
    out = {"type": t}
    if t in ("say", "ask"):
        k = "text" if t == "say" else "question"
        out[f"{k}_en"], out[f"{k}_de"] = _txt(s.get(f"{k}_en")), _txt(s.get(f"{k}_de"))
        if not out[f"{k}_en"] and not out[f"{k}_de"]:
            raise ValueError(f"'{t}' step needs a text")
    elif t == "gesture":
        if s.get("gesture") not in GESTURES:
            raise ValueError(f"Unknown gesture '{s.get('gesture')}'")
        out["gesture"] = s["gesture"]
    elif t == "walk":
        out["destination"] = _txt(s.get("destination"), 60)
        if not out["destination"]:
            raise ValueError("'walk' step needs a destination")
    elif t == "point":
        if s.get("target") not in TARGETS:
            raise ValueError(f"Unknown point target '{s.get('target')}'")
        out["target"] = s["target"]
    elif t == "wait":
        try:
            sec = float(s.get("seconds", 3))
        except (TypeError, ValueError):
            raise ValueError("'wait' needs seconds")
        if not 0.5 <= sec <= 300:
            raise ValueError("'wait' must be 0.5 - 300 s")
        out["seconds"] = round(sec, 1)
    elif t == "pause":
        out["text"] = _txt(s.get("text"), 120) or "Continue when ready"
    return out


def clean_show(sh: dict) -> dict:
    title = _txt(sh.get("title"), 80)
    if not title:
        raise ValueError("The show needs a title")
    steps = sh.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise ValueError("The show needs at least one step")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"Max {MAX_STEPS} steps per show")
    sid = re.sub(r"[^a-z0-9_-]", "", str(sh.get("id", "")).lower())[:40] or uuid.uuid4().hex[:10]
    return {"id": sid, "title": title, "lang": sh.get("lang") if sh.get("lang") in ("en", "de") else "en",
            "description": _txt(sh.get("description"), 200), "steps": [clean_step(s) for s in steps],
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}


EXAMPLE = {
    "id": "welcome_demo", "title": "Welcome demo (example)", "lang": "en",
    "description": "Greeting, a short explanation and a wave - no walking. Good first test.",
    "steps": [
        {"type": "say", "text_en": "Hello everyone, I'm G1. Welcome to the robotics lab of Furtwangen University!",
         "text_de": "Hallo zusammen, ich bin G1. Willkommen im Robotik-Labor der Hochschule Furtwangen!"},
        {"type": "gesture", "gesture": "high_wave"},
        {"type": "ask", "question_en": "What can you do?", "question_de": "Was kannst du?"},
        {"type": "pause", "text": "Visitors may ask questions now"},
        {"type": "say", "text_en": "Thank you for visiting. Enjoy the rest of your day!",
         "text_de": "Danke für Ihren Besuch. Einen schönen Tag noch!"},
    ],
}

_file_lock = threading.Lock()


def load_shows() -> list[dict]:
    try:
        with open(SHOWS_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return [dict(EXAMPLE, updated="")]


def _write(shows: list[dict]) -> None:
    os.makedirs(os.path.dirname(SHOWS_FILE), exist_ok=True)
    tmp = SHOWS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(shows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SHOWS_FILE)


def save_show(sh: dict) -> dict:
    show = clean_show(sh)
    with _file_lock:
        shows = [s for s in load_shows() if s.get("id") != show["id"]]
        if len(shows) >= MAX_SHOWS:
            raise ValueError(f"Max {MAX_SHOWS} shows")
        shows.append(show)
        _write(shows)
    return show


def delete_show(sid: str) -> None:
    with _file_lock:
        shows = load_shows()
        rest = [s for s in shows if s.get("id") != sid]
        if len(rest) == len(shows):
            raise KeyError(sid)
        _write(rest)


def get_show(sid: str) -> dict:
    for s in load_shows():
        if s.get("id") == sid:
            return s
    raise KeyError(sid)


def step_label(s: dict, lang: str = "en") -> str:
    t = s["type"]
    if t == "say":
        return "Say: " + (s.get(f"text_{lang}") or s.get("text_en") or s.get("text_de") or "")[:60]
    if t == "ask":
        return "Answer: " + (s.get(f"question_{lang}") or s.get("question_en") or s.get("question_de") or "")[:60]
    if t == "gesture":
        return "Gesture: " + s["gesture"].replace("_", " ")
    if t == "walk":
        return "Walk to " + s["destination"].replace("_", " ")
    if t == "point":
        return "Point at " + s["target"].replace("_", " ")
    if t == "wait":
        return f"Wait {s['seconds']:g} s"
    return "Pause: " + s.get("text", "")


# ---------------------------------------------------------------- runner
class Stopped(Exception):
    pass


class ShowRunner:
    """hw: object with preflight() -> (ok, why), say(text, lang) -> seconds, ask(q, lang) -> (answer, seconds),
    gesture(name, should_stop) -> str, walk(dest, lang, should_stop) -> str, point(target, lang, should_stop) -> str,
    stop_motion(). Results: "done" or an error text."""

    def __init__(self, hw, on_change=None, runs_file: str | None = None, sleep=time.sleep, clock=time.monotonic):
        self.hw, self.on_change = hw, on_change or (lambda s: None)
        self.runs_file = runs_file or RUNS_FILE
        self.sleep, self.clock = sleep, clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._continue = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = {"state": "idle", "show": None, "title": "", "step": -1, "steps": 0, "label": "",
                      "message": "", "mode": "auto", "lang": "en", "log": [], "labels": []}

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self.state))

    def _set(self, **kw) -> None:
        with self._lock:
            self.state.update(kw)
        try:
            self.on_change(self.snapshot())
        except Exception:
            pass

    @property
    def busy(self) -> bool:
        return self.state["state"] in ("running", "waiting")

    def start(self, show: dict, mode: str = "auto", lang: str | None = None, start_at: int = 0,
              background: bool = True) -> dict:
        if self.busy:
            raise RuntimeError("A show is already running - stop it first")
        lang = lang if lang in ("en", "de") else show.get("lang", "en")
        steps = show["steps"]
        if not 0 <= start_at < len(steps):
            raise ValueError("start step out of range")
        self._stop.clear()
        self._continue.clear()
        self._set(state="running", show=show["id"], title=show["title"], step=start_at, steps=len(steps),
                  label="", message="", mode="step" if mode == "step" else "auto", lang=lang, log=[],
                  labels=[step_label(s, lang) for s in steps], started=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if background:
            self._thread = threading.Thread(target=self._run, args=(show, lang, start_at), daemon=True)
            self._thread.start()
        else:
            self._run(show, lang, start_at)
        return self.snapshot()

    def stop(self) -> dict:
        if not self.busy:                     # never cancel motion that the show did not start
            return self.snapshot()
        self._stop.set()
        self._continue.set()
        try:
            self.hw.stop_motion()
        except Exception:
            pass
        self._set(message="Stopping…")
        return self.snapshot()

    def next(self) -> dict:
        if self.state["state"] != "waiting":
            raise RuntimeError("Nothing to continue")
        self._continue.set()
        return self.snapshot()

    def _should_stop(self) -> bool:
        return self._stop.is_set()

    def _wait(self, seconds: float) -> None:
        end = self.clock() + seconds
        while self.clock() < end:
            if self._stop.is_set():
                raise Stopped()
            self.sleep(min(0.2, max(0.0, end - self.clock())))

    def _wait_operator(self, message: str) -> None:
        self._continue.clear()
        self._set(state="waiting", message=message)
        while not self._continue.wait(0.2):
            pass
        if self._stop.is_set():
            raise Stopped()
        self._set(state="running", message="")

    def _do(self, s: dict, lang: str) -> str:
        t = s["type"]
        if t in MOTION:
            ok, why = self.hw.preflight()
            if not ok:
                return f"not safe to move: {why}"
        if t == "say":
            text = s.get(f"text_{lang}") or s.get("text_en") or s.get("text_de")
            self._wait(self.hw.say(text, lang))
            return "done"
        if t == "ask":
            q = s.get(f"question_{lang}") or s.get("question_en") or s.get("question_de")
            answer, seconds = self.hw.ask(q, lang)
            self._set(message=answer[:200])
            self._wait(seconds)
            return "done"
        if t == "gesture":
            return self.hw.gesture(s["gesture"], self._should_stop)
        if t == "walk":
            return self.hw.walk(s["destination"], lang, self._should_stop)
        if t == "point":
            return self.hw.point(s["target"], lang, self._should_stop)
        if t == "wait":
            self._wait(s["seconds"])
            return "done"
        if t == "pause":
            self._wait_operator(s.get("text") or "Continue when ready")
            return "done"
        return f"unknown step {t}"

    def _run(self, show: dict, lang: str, start_at: int) -> None:
        t0, steps, result, failed = self.clock(), show["steps"], "done", None
        i = start_at
        try:
            for i in range(start_at, len(steps)):
                s = steps[i]
                label = step_label(s, lang)
                self._set(step=i, label=label, message="")
                ts = self.clock()
                try:
                    res = self._do(s, lang)
                except Stopped:
                    raise
                except Exception as exc:
                    res = f"error: {exc}"
                if self._stop.is_set():
                    raise Stopped()
                entry = {"i": i, "type": s["type"], "label": label, "result": "done" if res == "done" else "failed",
                         "seconds": round(self.clock() - ts, 1), "message": "" if res == "done" else res}
                self._set(log=self.state["log"] + [entry])
                if res != "done":
                    result, failed = "failed", i
                    self._set(state="failed", message=f"Step {i + 1} failed: {res}")
                    try:
                        self.hw.stop_motion()
                    except Exception:
                        pass
                    break
                if self.state["mode"] == "step" and i < len(steps) - 1 and s["type"] != "pause":
                    self._wait_operator(f"Step {i + 1} done - continue with: {step_label(steps[i + 1], lang)}")
            else:
                self._set(state="done", label="", message="Show finished")
        except Stopped:
            result = "stopped"
            self._set(state="stopped", message=f"Stopped at step {i + 1}")
        except Exception as exc:                                    # never leave it "running"
            result, failed = "failed", i
            self._set(state="failed", message=str(exc))
        self._record(show, lang, result, failed, t0)

    def _record(self, show, lang, result, failed, t0) -> None:
        st = self.snapshot()
        rec = {"started": st.get("started"), "show": show["id"], "title": show["title"], "lang": lang,
               "mode": st["mode"], "result": result, "duration_s": round(self.clock() - t0, 1),
               "steps_total": len(show["steps"]), "steps_done": sum(1 for e in st["log"] if e["result"] == "done"),
               "failed_step": failed, "message": st["message"], "log": st["log"]}
        try:
            os.makedirs(os.path.dirname(self.runs_file), exist_ok=True)
            with open(self.runs_file, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass


def load_runs(path: str | None = None) -> list[dict]:
    out = []
    try:
        with open(path or RUNS_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- the real robot
class RobotHw:
    ACTIVE_GUIDE = ("starting", "planning", "walking", "guiding", "blocked", "returning", "turning",
                    "aligning", "replanning", "waiting", "speaking", "arrived")
    END_GUIDE_OK = ("done",)
    END_GUIDE_BAD = ("aborted", "cancelled", "failed", "error")

    def __init__(self, loop=None):
        self.loop = loop

    def preflight(self):
        from app.services import attract_service
        return attract_service._idle()

    def _after_speech(self, text: str, ends_ms) -> float:
        from app.services import talk_gestures, voice_listener
        seconds = ends_ms / 1000.0 if isinstance(ends_ms, int) else 0.075 * len(text) + 1.0
        lst = voice_listener.get()
        if lst is not None:
            lst.remember_reply(text)
            lst.mute_for(seconds + 0.5)
        talk_gestures.gesture_for(text, ends_ms)
        return seconds + 0.4

    def say(self, text: str, lang: str) -> float:
        from app.services import content_service, interaction_control
        body = content_service.say_on_g1(text, lang)
        interaction_control.record("operator", "", text, lang, None, spoke=True, note="show")
        return self._after_speech(text, (body or {}).get("ends_in_ms"))

    def ask(self, question: str, lang: str):
        import asyncio
        from app.services.interaction_service import interaction_service
        fut = asyncio.run_coroutine_threadsafe(
            interaction_service.ask(question=question, speak=True, language=lang, source="studio"), self.loop)
        res = fut.result(timeout=120)
        ends = res.get("speech_ends_in_ms")
        answer = res.get("answer", "")
        seconds = ends / 1000.0 if isinstance(ends, int) else 0.075 * len(answer) + 1.0
        from app.services import voice_listener
        lst = voice_listener.get()
        if lst is not None:
            lst.remember_reply(answer)
            lst.mute_for(seconds + 0.5)
        return answer, seconds + 0.4

    def gesture(self, name: str, should_stop) -> str:
        from app.services import robot_hub
        code, body = robot_hub.post_json(f"{robot_hub.TELEOP}/api/teleop/voice/gesture", {"gesture": name}, timeout=4)
        if code >= 400:
            return f"gesture refused: {(body or {}).get('detail', code)}"
        end = time.monotonic() + 15
        time.sleep(1.0)
        while time.monotonic() < end:                     # wait until the gesture is over
            if should_stop():
                return "stopped"
            try:
                t = robot_hub.get_json(f"{robot_hub.TELEOP}/api/teleop/status", timeout=1.5) or {}
                if not t.get("gesture"):
                    return "done"
            except Exception:
                pass
            time.sleep(0.3)
        return "done"

    def walk(self, destination: str, lang: str, should_stop) -> str:
        from app.services import destinations_service as dest, robot_hub
        try:
            d = dest.get(destination)
        except KeyError:
            return f"unknown destination '{destination}'"
        payload = {k: d.get(k) for k in ("x", "y", "yaw", "name", "title_en", "title_de", "arrival_en", "arrival_de")}
        payload["lang"] = lang
        code, body = robot_hub.guide_goto(payload)
        if code >= 400:
            return f"could not start walking: {(body or {}).get('detail', code)}"
        seen, t_end = False, time.monotonic() + 300
        while time.monotonic() < t_end:
            if should_stop():
                robot_hub.guide_cancel()
                return "stopped"
            try:
                g = robot_hub.guide_status() or {}
            except Exception:
                g = {}
            st = g.get("state")
            if st in self.ACTIVE_GUIDE and st != "arrived":
                seen = True
            elif seen and st in self.END_GUIDE_OK + ("arrived",):
                return "done"
            elif seen and st == "idle":
                return "done" if (g.get("progress") or 0) >= 0.99 else "walk ended early"
            elif seen and st in self.END_GUIDE_BAD:
                return f"walk {st}: {g.get('message', '')}"
            time.sleep(0.3)
        robot_hub.guide_cancel()
        return "walk timed out (5 min)"

    def point(self, target: str, lang: str, should_stop) -> str:
        from app.services import robot_hub
        code, body = robot_hub.pick_point(target, lang)
        if code >= 400:
            return f"point refused: {(body or {}).get('detail', code)}"
        seen, t_end = False, time.monotonic() + 120
        while time.monotonic() < t_end:
            if should_stop():
                robot_hub.pick_stop()
                return "stopped"
            try:
                p = robot_hub.pick_status() or {}
            except Exception:
                p = {}
            st = p.get("state")
            if st in ("looking", "moving", "approach", "hover", "pointing", "returning"):
                seen = True
            elif st == "done" and seen:
                return "done"
            elif st in ("failed", "refused", "stopped") and (seen or p.get("target") == target):
                return f"point {st}: {p.get('message', '')}"
            time.sleep(0.3)
        robot_hub.pick_stop()
        return "point timed out"

    def stop_motion(self) -> None:
        from app.services import robot_hub
        for fn in (robot_hub.guide_cancel, robot_hub.pick_stop):
            try:
                fn()
            except Exception:
                pass


runner: ShowRunner | None = None


def get_runner(loop=None, broadcast=None) -> ShowRunner:
    global runner
    if runner is None:
        last = {"key": None}

        def changed(s: dict) -> None:
            if broadcast:
                broadcast({"type": "show", "data": s})
            key = (s.get("state"), s.get("step"), s.get("label"))
            if key == last["key"]:
                return
            last["key"] = key
            try:
                from app.services import activity_service as act
                if s["state"] == "running" and s.get("label"):
                    act.add_event("show", f"Show “{s['title']}” – step {s['step'] + 1}/{s['steps']}", s["label"])
                elif s["state"] == "waiting":
                    act.add_event("show", "Show waiting for the operator", s.get("message", ""))
                elif s["state"] in ("done", "failed", "stopped"):
                    act.add_event("show", f"Show {s['state']}: {s['title']}", s.get("message", ""),
                                  "ok" if s["state"] == "done" else "warn")
            except Exception:
                pass
        runner = ShowRunner(RobotHw(loop), on_change=changed)
    return runner
