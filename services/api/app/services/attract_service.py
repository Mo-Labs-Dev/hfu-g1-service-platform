"""
Attract mode: when nobody is using G1, it notices people walking past
(head camera + YOLO person detection), waves and invites them.

Switched on/off in G1 Studio (Visitor App page). Only acts when G1 is idle:
walking mode, no guide/tour/vision task, joystick not in use, no E-stop,
battery not critical - and at most once per cooldown. The wave uses the
visitor gesture endpoint of the teleop server (same safety rules as the
Robot Show: robot standing still, gesture cooldown, demo mode on).
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time

from app.services import robot_hub
from app.services.lab_map_service import _DATA

SETTINGS_FILE = os.path.expanduser(os.getenv("G1_ATTRACT_FILE", os.path.join(_DATA, "attract.json")))

DEFAULT = {
    "enabled": False,
    "cooldown_s": 120,           # at most one greeting per 2 minutes
    "min_box_height": 0.25,      # person box height / image height (closer people are bigger)
    "frames_needed": 2,          # seen in 2 pictures in a row
    "wave": True,
    "text_en": "Hello! I'm G1. Would you like a lab tour? Just tap Start on the tablet.",
    "text_de": "Hallo! Ich bin G1. Möchten Sie eine Laborführung? Tippen Sie einfach auf Start am Tablet.",
    "languages": ["en", "de"],
}

_lock = threading.Lock()


def load() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    cfg = dict(DEFAULT)
    cfg.update({k: v for k, v in data.items() if k in DEFAULT})
    return cfg


def save(change: dict) -> dict:
    with _lock:
        cfg = load()
        if "enabled" in change:
            cfg["enabled"] = bool(change["enabled"])
        if "wave" in change:
            cfg["wave"] = bool(change["wave"])
        if "cooldown_s" in change:
            cfg["cooldown_s"] = int(max(30, min(1800, int(change["cooldown_s"]))))
        if "min_box_height" in change:
            cfg["min_box_height"] = float(max(0.05, min(0.9, float(change["min_box_height"]))))
        for k in ("text_en", "text_de"):
            if k in change and change[k] is not None:
                cfg[k] = str(change[k]).strip()[:300] or DEFAULT[k]
        if "languages" in change and isinstance(change["languages"], list):
            langs = [x for x in change["languages"] if x in ("en", "de")]
            cfg["languages"] = langs or ["en"]
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(cfg, f, indent=1, ensure_ascii=False)
        return cfg


class AttractLogic:
    """Pure decision logic (unit tested)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.streak = 0
        self.last_greet: float | None = None
        self.greetings_today = 0
        self.day = time.strftime("%Y-%m-%d")
        self.last_person: float | None = None
        self.state = "off"
        # Greet only NEW arrivals: after a greeting the view must be empty for a while
        # (staff working in front of G1 is not greeted every 2 minutes).
        self.need_clear = False
        self.empty_frames = 0
        self.clear_frames = 6           # ~10 s without a person

    def person_in(self, detections: list, image_h: float, min_box: float) -> bool:
        for d in detections:
            if d.get("label") != "person" or d.get("confidence", 0) < 0.5:
                continue
            b = d.get("bbox", {})
            if (b.get("y2", 0) - b.get("y1", 0)) / max(1.0, image_h) >= min_box:
                return True
        return False

    def step(self, cfg: dict, idle: bool, why_not: str, person: bool) -> bool:
        """Returns True when G1 should greet now."""
        now = self.clock()
        today = time.strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.greetings_today = today, 0
        if not cfg["enabled"]:
            self.state, self.streak = "off", 0
            return False
        if not idle:
            self.state, self.streak = f"paused: {why_not}", 0
            return False
        self.empty_frames = 0 if person else self.empty_frames + 1
        if self.need_clear and self.empty_frames >= self.clear_frames:
            self.need_clear = False
        if self.last_greet is not None and now - self.last_greet < cfg["cooldown_s"]:
            self.state = f"cooldown ({int(cfg['cooldown_s'] - (now - self.last_greet))} s)"
            self.streak = 0
            return False
        if self.need_clear:
            self.state = "waiting for new visitors"
            self.streak = 0
            return False
        self.streak = self.streak + 1 if person else 0
        if person:
            self.last_person = now
        self.state = "watching" if not person else f"person seen ({self.streak}/{cfg['frames_needed']})"
        if self.streak >= cfg["frames_needed"]:
            self.last_greet, self.streak = now, 0
            self.need_clear, self.empty_frames = True, 0
            self.greetings_today += 1
            self.state = "greeting"
            return True
        return False


logic = AttractLogic()


def _idle() -> tuple[bool, str]:
    try:
        t = robot_hub.get_json(f"{robot_hub.TELEOP}/api/teleop/status", timeout=1.5) or {}
    except Exception:
        return False, "teleop not reachable"
    if t.get("estop"):
        return False, "E-stop"
    if t.get("fsm_id") != 500:
        return False, "not in walking mode"
    if t.get("teleop_active"):
        return False, "joystick in use"
    if t.get("gesture"):
        return False, "gesture running"
    try:
        g = robot_hub.get_json(f"{robot_hub.GUIDE}/api/guide/status", timeout=1.0) or {}
        if g.get("state") not in (None, "idle", "done", "aborted", "cancelled"):
            return False, "guide running"
    except Exception:
        pass
    try:
        v = robot_hub.get_json(f"{robot_hub.VISION}/api/vision/status", timeout=1.0) or {}
        if v.get("state") in ("describing", "searching", "turning"):
            return False, "vision task running"
    except Exception:
        pass
    try:
        from app.services.battery_watch import watch
        if watch.level == "critical":
            return False, "battery critical"
    except Exception:
        pass
    return True, ""


def _look(min_box: float) -> bool:
    from app.services.vision_service import vision_service
    jpeg, _ = robot_hub.camera_snapshot()
    res = vision_service.detect(jpeg, 0.45)
    h = float((res.get("image") or {}).get("height") or 1080)
    return logic.person_in(res.get("detections", []), h, min_box)


def greet(cfg: dict) -> None:
    from app.services import content_service
    if cfg.get("wave"):
        try:
            robot_hub.post_json(f"{robot_hub.TELEOP}/api/teleop/voice/gesture", {"gesture": "high_wave"}, timeout=3)
        except Exception as exc:
            print(f"[attract] wave skipped: {exc}")
    for lang in cfg.get("languages", ["en"]):
        try:
            content_service.say_on_g1(cfg["text_de"] if lang == "de" else cfg["text_en"], lang)
        except Exception as exc:
            print(f"[attract] speech failed: {exc}")


async def run_forever() -> None:
    from fastapi.concurrency import run_in_threadpool
    from app.api.websocket import manager

    while True:
        cfg = load()
        try:
            if not cfg["enabled"]:
                logic.step(cfg, True, "", False)
                await asyncio.sleep(3.0)
                continue
            idle, why = await run_in_threadpool(_idle)
            person = False
            if idle:
                try:
                    person = await run_in_threadpool(_look, cfg["min_box_height"])
                except Exception:
                    person = False
            if logic.step(cfg, idle, why, person):
                await run_in_threadpool(greet, cfg)
                await manager.broadcast({"type": "attract", "data": {"greetings_today": logic.greetings_today}})
                print(f"[attract] greeted a visitor ({logic.greetings_today} today)")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logic.state = f"error: {exc}"
        await asyncio.sleep(1.5)


def status() -> dict:
    now = time.monotonic()
    return {"settings": load(), "state": logic.state, "greetings_today": logic.greetings_today,
            "last_greet_s_ago": round(now - logic.last_greet) if logic.last_greet else None,
            "last_person_s_ago": round(now - logic.last_person) if logic.last_person else None}
