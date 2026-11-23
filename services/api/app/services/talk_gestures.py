"""Co-speech gestures: while G1 speaks a chat answer, its arms move like a person explaining.
The robot service (port 8005) does the motion with all its safety checks; this only switches it
on/off (data/talk_gestures.json, off until tested) and starts it for each spoken answer."""
from __future__ import annotations

import json
import os
import threading

from app.services import robot_hub

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
FILE = os.path.join(_DATA, "talk_gestures.json")


def enabled() -> bool:
    try:
        with open(FILE) as f:
            return bool(json.load(f).get("enabled"))
    except (OSError, ValueError):
        return False


def set_enabled(on: bool) -> None:
    os.makedirs(_DATA, exist_ok=True)
    with open(FILE, "w") as f:
        json.dump({"enabled": bool(on)}, f)


def speech_seconds(text: str, ends_in_ms=None) -> float:
    """How long G1 will talk: the voice bridge's number when it is plausible, never less than
    the length of the text needs (the bridge sometimes reports only a short queue time)."""
    estimate = 0.075 * len(text or "") + 1.0
    if isinstance(ends_in_ms, int) and ends_in_ms > 0:
        return max(ends_in_ms / 1000.0, estimate)
    return estimate


def gesture_for(text: str, ends_in_ms=None) -> None:
    """Fire and forget - talking never waits for the arms."""
    if not enabled() or not (text or "").strip():
        return
    seconds = speech_seconds(text, ends_in_ms)
    if seconds < 2.5:                      # "Yes?" etc. - no gestures for very short answers
        return

    def go():
        try:
            robot_hub.post_json(f"{robot_hub.PICK}/api/pick/talk", {"seconds": seconds}, timeout=3)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()
