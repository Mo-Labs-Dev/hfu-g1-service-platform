"""
G1 Vision core logic (no network - unit tested).

  describe: camera picture -> local vision-language model -> short spoken answer
  find:     turn on the spot in steps, YOLO looks for the object, turn to face it,
            announce + wave.
"""
from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field

# Visitor words (EN / DE) -> YOLO (COCO) labels.
OBJECTS: dict[str, tuple[str, ...]] = {
    "person": ("person", "people", "human", "someone", "somebody", "man", "woman", "student",
               "person", "mensch", "menschen", "jemand", "mann", "frau", "student", "studentin", "leute"),
    "bottle": ("bottle", "water bottle", "flasche", "wasserflasche"),
    "cup": ("cup", "mug", "coffee cup", "tasse", "becher", "kaffeetasse"),
    "chair": ("chair", "seat", "stuhl", "sessel"),
    "laptop": ("laptop", "notebook", "computer", "laptop", "rechner"),
    "keyboard": ("keyboard", "tastatur"),
    "mouse": ("computer mouse", "mouse", "maus"),
    "cell phone": ("phone", "cell phone", "mobile", "smartphone", "handy", "telefon"),
    "book": ("book", "buch"),
    "backpack": ("backpack", "bag", "rucksack", "tasche"),
    "potted plant": ("plant", "flower", "pflanze", "blume"),
    "tv": ("tv", "screen", "monitor", "television", "bildschirm", "fernseher"),
    "clock": ("clock", "uhr"),
    "scissors": ("scissors", "schere"),
    "dining table": ("table", "desk", "tisch", "schreibtisch"),
    "umbrella": ("umbrella", "regenschirm", "schirm"),
    "sports ball": ("ball",),
    "teddy bear": ("teddy", "teddy bear", "teddybär", "teddybaer"),
}

NAMES = {   # how G1 says the label
    "en": {"person": "person", "bottle": "bottle", "cup": "cup", "chair": "chair", "laptop": "laptop",
           "keyboard": "keyboard", "mouse": "computer mouse", "cell phone": "phone", "book": "book",
           "backpack": "backpack", "potted plant": "plant", "tv": "screen", "clock": "clock",
           "scissors": "scissors", "dining table": "table", "umbrella": "umbrella",
           "sports ball": "ball", "teddy bear": "teddy bear"},
    "de": {"person": "eine Person", "bottle": "eine Flasche", "cup": "eine Tasse", "chair": "einen Stuhl",
           "laptop": "einen Laptop", "keyboard": "eine Tastatur", "mouse": "eine Maus",
           "cell phone": "ein Handy", "book": "ein Buch", "backpack": "einen Rucksack",
           "potted plant": "eine Pflanze", "tv": "einen Bildschirm", "clock": "eine Uhr",
           "scissors": "eine Schere", "dining table": "einen Tisch", "umbrella": "einen Regenschirm",
           "sports ball": "einen Ball", "teddy bear": "einen Teddybären"},
}

TEXT = {
    "search": {"en": "Okay, let me look for the {o}.", "de": "Okay, ich suche {o}."},
    "found": {"en": "I found the {o}! It is right there.", "de": "Ich habe {o} gefunden! Dort ist es."},
    "not_found": {"en": "Sorry, I could not find the {o} around me.",
                  "de": "Tut mir leid, ich konnte {o} hier nicht finden."},
    "unknown": {"en": "Sorry, I can not recognise that object yet.",
                "de": "Tut mir leid, diesen Gegenstand kann ich noch nicht erkennen."},
}

DESCRIBE_PROMPT = {
    "en": ("You are G1, a friendly humanoid robot in a university lab. This is what your camera "
           "sees right now. Answer the visitor in at most two short sentences that sound natural "
           "when spoken, in English. Do not say 'image' or 'picture'. Visitor: {q}"),
    "de": ("Du bist G1, ein freundlicher humanoider Roboter in einem Hochschullabor. Das sieht "
           "deine Kamera gerade. Antworte dem Besucher in höchstens zwei kurzen, natürlich "
           "gesprochenen Sätzen auf Deutsch. Sag nicht 'Bild' oder 'Foto'. Besucher: {q}"),
}


def find_target(text: str) -> str | None:
    """Which COCO label does the visitor ask for? Longest synonym wins."""
    t = " " + re.sub(r"[^\wäöüß ]", " ", text.lower()) + " "
    best, best_len = None, 0
    for label, words in OBJECTS.items():
        for w in words:
            if f" {w} " in t or (len(w) > 4 and w in t):
                if len(w) > best_len:
                    best, best_len = label, len(w)
    return best


def best_detection(result: dict, label: str, min_conf: float):
    dets = [d for d in result.get("detections", [])
            if d.get("label") == label and d.get("confidence", 0) >= min_conf]
    return max(dets, key=lambda d: d["confidence"]) if dets else None


def bearing(det: dict, width: float, hfov_deg: float) -> float:
    """Angle to the object, radians, + = left (robot yaw convention)."""
    b = det["bbox"]
    cx = (b["x1"] + b["x2"]) / 2.0
    return -math.radians((cx / width - 0.5) * hfov_deg)


@dataclass
class FindParams:
    step_deg: float = 30.0          # turn between looks
    max_steps: int = 12             # 12 x 30 = full circle
    turn_rate: float = 0.35         # rad/s while turning
    settle_s: float = 1.0           # wait after turning before taking a picture
    hfov_deg: float = 69.0          # head camera horizontal field of view
    min_conf: float = 0.40
    center_tol_deg: float = 6.0
    accel: float = 1.0              # rad/s^2 of the teleop server ramp


@dataclass
class VisionStatus:
    state: str = "idle"             # idle describing searching turning found not_found cancelled error
    task: str = ""                  # describe / find
    target: str = ""
    message: str = ""
    answer: str = ""
    step: int = 0
    turned_deg: float = 0.0
    history: list = field(default_factory=list)


class Cancelled(Exception):
    pass


class VisionRunner:
    """
    camera  - snapshot() -> jpeg bytes
    detector- detect(jpeg) -> {"image": {"width"}, "detections": [...]}
    vlm     - ask(jpeg, prompt) -> text
    motion  - begin(), end(), send(x, yaw), status(), gesture(name), stopped_by_operator()
    voice   - say(text, lang) -> dict | None
    """

    def __init__(self, camera, detector, vlm, motion, voice, params: FindParams | None = None,
                 clock=time.monotonic, sleep=time.sleep):
        self.camera, self.detector, self.vlm = camera, detector, vlm
        self.motion, self.voice = motion, voice
        self.p = params or FindParams()
        self.clock, self.sleep = clock, sleep
        self.status = VisionStatus()
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            s = self.status
            return {"state": s.state, "task": s.task, "target": s.target, "message": s.message,
                    "answer": s.answer, "step": s.step, "turned_deg": round(s.turned_deg, 1)}

    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self.status, k, v)
            if "state" in kw:
                self.status.history.append((round(self.clock(), 2), kw["state"]))

    def cancel(self):
        self._cancel.set()

    def _say(self, text: str, lang: str) -> None:
        try:
            self.voice.say(text, lang)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def describe(self, question: str = "", lang: str = "en") -> str:
        lang = lang if lang in ("en", "de") else "en"
        q = question.strip() or ("What do you see?" if lang == "en" else "Was siehst du?")
        self._cancel.clear()
        self._set(state="describing", task="describe", target="", answer="", message="Looking ...")
        try:
            jpeg = self.camera.snapshot()
            answer = self.vlm.ask(jpeg, DESCRIBE_PROMPT[lang].format(q=q)).strip()
            answer = answer or ("I am not sure what I see." if lang == "en" else "Ich bin mir nicht sicher.")
            self._say(answer, lang)
            self._set(state="idle", answer=answer, message="")
            return answer
        except Exception as exc:
            self._set(state="error", message=f"Vision not available: {exc}")
            raise

    # ------------------------------------------------------------------
    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()
        st = self.motion.status()
        if st.get("estop"):
            raise RuntimeError("Software E-stop is active.")
        if self.motion.stopped_by_operator():
            raise Cancelled()
        if st.get("fsm_id") not in (None, 500):
            raise RuntimeError(f"Robot left walking mode (FSM {st.get('fsm_id')}).")

    def _hold(self, seconds: float) -> None:
        end = self.clock() + seconds
        while self.clock() < end:
            self._check()
            self.motion.send(0.0, 0.0)            # keep the lease alive, stand still
            self.sleep(0.1)

    def _turn(self, angle: float, max_yaw: float) -> None:
        """Timed turn on the spot (no odometry needed). + = left."""
        if abs(angle) < 1e-3:
            return
        rate = min(self.p.turn_rate, max_yaw)
        norm = math.copysign(rate / max_yaw, angle)
        duration = abs(angle) / rate + 0.5 * rate / self.p.accel     # ramp-up compensation
        self._set(state="turning")
        end = self.clock() + duration
        while self.clock() < end:
            self._check()
            self.motion.send(0.0, norm)
            self.sleep(0.1)
        with self._lock:
            self.status.turned_deg += math.degrees(angle)
        self._hold(self.p.settle_s)

    def _look(self, label: str):
        jpeg = self.camera.snapshot()
        res = self.detector.detect(jpeg)
        det = best_detection(res, label, self.p.min_conf)
        width = float(res.get("image", {}).get("width") or 1920)
        return det, width

    def find(self, text_or_label: str, lang: str = "en") -> str:
        lang = lang if lang in ("en", "de") else "en"
        label = text_or_label if text_or_label in OBJECTS else find_target(text_or_label)
        self._cancel.clear()
        if label is None:
            self._set(state="not_found", task="find", target="", message="Unknown object")
            self._say(TEXT["unknown"][lang], lang)
            return "unknown"
        name = NAMES[lang][label]
        self._set(state="searching", task="find", target=label, step=0, turned_deg=0.0,
                  answer="", message=f"Looking for {label}")
        st = self.motion.status()
        if st.get("estop") or st.get("fsm_id") != 500 or st.get("teleop_active") or st.get("gesture"):
            self._set(state="error", message="Robot not ready (walking mode, joystick locked, no E-stop).")
            return "error"
        max_yaw = float(st.get("limits", {}).get("max_yaw") or 0.4)
        self.motion.begin()
        try:
            self._say(TEXT["search"][lang].format(o=name), lang)
            for step in range(self.p.max_steps):
                self._set(state="searching", step=step + 1)
                self._hold(0.3)
                det, width = self._look(label)
                if det is not None:
                    ang = bearing(det, width, self.p.hfov_deg)
                    if abs(math.degrees(ang)) > self.p.center_tol_deg:
                        self._turn(ang, max_yaw)
                        det2, width2 = self._look(label)       # confirm + refine once
                        if det2 is not None:
                            ang2 = bearing(det2, width2, self.p.hfov_deg)
                            if abs(math.degrees(ang2)) > self.p.center_tol_deg:
                                self._turn(ang2, max_yaw)
                    text = TEXT["found"][lang].format(o=name)
                    self._set(state="found", answer=text, message=f"Found {label} ({det['confidence']:.0%})")
                    self._say(text, lang)
                    try:
                        self.motion.gesture("high_wave")
                        self.sleep(3.5)                    # let the wave finish before releasing
                    except Exception:
                        pass
                    return "found"
                if step < self.p.max_steps - 1:
                    self._turn(math.radians(self.p.step_deg), max_yaw)
            text = TEXT["not_found"][lang].format(o=name)
            self._set(state="not_found", answer=text, message="Not found after a full turn")
            self._say(text, lang)
            return "not_found"
        except Cancelled:
            self.motion.send(0.0, 0.0)
            self._set(state="cancelled", message="Cancelled")
            return "cancelled"
        except Exception as exc:
            self.motion.send(0.0, 0.0)
            self._set(state="error", message=str(exc))
            return "error"
        finally:
            try:
                self.motion.end()
            except Exception:
                pass
