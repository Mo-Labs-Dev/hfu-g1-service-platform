"""
Interaction control - one place in G1 Studio that sees and steers every conversation with G1.

Sources of a conversation turn:
  app      - visitor typed / spoke in the G1 Remote app (Talk screen)
  mic      - visitor spoke to G1 directly ("Hey G1 ..." into the robot microphone)
  studio   - operator test question from the Studio Interaction page
  operator - operator typed a sentence and G1 said it word for word

Settings (data/interaction_settings.json), changed in Studio with the operator PIN:
  app_talk       False -> the app gets a friendly "not taking questions" reply, the LLM is not asked
  speak_answers  False -> answers are only shown as text, G1 stays silent (quiet lab)
  reply_length   short | normal | long  -> spoken length of answers
  note_en        extra instruction for today, e.g. "Today is open house day - invite people to station 3"

Every turn is kept (last 300 in memory, all in data/interaction_log.jsonl) and broadcast to
Studio over the WebSocket as {"type": "interaction", "data": {...}}.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
SETTINGS_FILE = os.path.expanduser(os.getenv("G1_INTERACTION_SETTINGS", os.path.join(_DATA, "interaction_settings.json")))
LOG_FILE = os.path.expanduser(os.getenv("G1_INTERACTION_LOG", os.path.join(_DATA, "interaction_log.jsonl")))

SOURCES = ("app", "mic", "studio", "operator")
LENGTHS = {
    "short": ("Answer in one or two short sentences.", 120),
    "normal": ("Answer usually in 1 to 3 short sentences.", 250),
    "long": ("You may answer in up to 5 sentences when the question needs it.", 400),
}
NOTE_MAX = 500
DEFAULT = {"app_talk": True, "speak_answers": True, "reply_length": "normal", "note": ""}
PAUSED_REPLY = {
    "en": "Sorry, I'm not taking questions in the app right now. Please ask a member of the lab team.",
    "de": "Entschuldigung, ich beantworte gerade keine Fragen über die App. Bitte fragen Sie das Laborteam.",
}

_lock = threading.Lock()
_log: deque = deque(maxlen=300)
_loaded_log = False
_seq = 0
broadcaster = None            # set in main.py: callable(event dict) -> None (thread safe)


# ---------------------------------------------------------------- settings
def load_settings() -> dict:
    s = dict(DEFAULT)
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            s.update({k: data[k] for k in DEFAULT if k in data})
    except (OSError, ValueError):
        pass
    if s["reply_length"] not in LENGTHS:
        s["reply_length"] = "normal"
    s["app_talk"], s["speak_answers"] = bool(s["app_talk"]), bool(s["speak_answers"])
    s["note"] = str(s["note"] or "")[:NOTE_MAX]
    return s


def save_settings(change: dict) -> dict:
    with _lock:
        s = load_settings()
        for k in ("app_talk", "speak_answers"):
            if k in change and change[k] is not None:
                s[k] = bool(change[k])
        if change.get("reply_length") is not None:
            if change["reply_length"] not in LENGTHS:
                raise ValueError("reply_length must be short, normal or long")
            s["reply_length"] = change["reply_length"]
        if change.get("note") is not None:
            note = " ".join(str(change["note"]).split())
            if len(note) > NOTE_MAX:
                raise ValueError(f"Note is too long (max {NOTE_MAX} characters)")
            s["note"] = note
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    _emit({"type": "interaction_settings", "data": s})
    return s


def prompt_extras(settings: dict | None = None) -> tuple[list[dict], int]:
    """Extra system messages + num_predict for the chat model."""
    s = settings or load_settings()
    rule, tokens = LENGTHS[s["reply_length"]]
    msgs = [{"role": "system", "content": "LENGTH: " + rule}]
    if s["note"]:
        msgs.append({"role": "system", "content":
                     "NOTE FROM THE LAB TEAM FOR TODAY (use it when it fits, never read it out word by word): "
                     + s["note"]})
    return msgs, tokens


# ---------------------------------------------------------------- log
def _load_log() -> None:
    global _loaded_log, _seq
    if _loaded_log:
        return
    _loaded_log = True
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()[-_log.maxlen:]
        for line in lines:
            try:
                e = json.loads(line)
                _log.append(e)
                _seq = max(_seq, int(e.get("id", 0)))
            except ValueError:
                continue
    except OSError:
        pass


def record(source: str, heard: str, reply: str | None, lang: str = "en",
           seconds: float | None = None, spoke: bool = False, note: str = "") -> dict:
    global _seq
    if source not in SOURCES:
        source = "app"
    with _lock:
        _load_log()
        _seq += 1
        entry = {
            "id": _seq,
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": source,
            "heard": (heard or "")[:1000],
            "reply": (reply or "")[:1000],
            "lang": lang if lang in ("en", "de") else "en",
            "seconds": None if seconds is None else round(float(seconds), 2),
            "spoke": bool(spoke),
            "note": note,
        }
        _log.append(entry)
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
    _emit({"type": "interaction", "data": entry})
    try:                                           # Live view: "what is G1 doing"
        from app.services import activity_service
        who = {"app": "Visitor (app)", "mic": "Visitor (to G1)", "studio": "Studio test"}.get(source)
        if who:
            activity_service.add_event("talk", f"{who}: “{entry['heard'][:120]}”", "G1: " + entry["reply"][:250])
        elif entry["note"] != "show":
            activity_service.add_event("talk", f"G1 said: “{entry['reply'][:150]}”")
    except Exception:
        pass
    return entry


def recent(limit: int = 100) -> list[dict]:
    with _lock:
        _load_log()
        return list(_log)[-max(1, min(limit, _log.maxlen)):]


def clear_view() -> None:
    """Clears the Studio list only - the jsonl file stays (thesis evaluation data)."""
    with _lock:
        _load_log()
        _log.clear()
    _emit({"type": "interaction_cleared", "data": {}})


def stats() -> dict:
    today = time.strftime("%Y-%m-%d")
    with _lock:
        _load_log()
        items = [e for e in _log if str(e.get("t", "")).startswith(today)]
    by_source = {s: sum(1 for e in items if e["source"] == s) for s in SOURCES}
    times = [e["seconds"] for e in items if e.get("seconds") is not None and e["source"] in ("app", "mic", "studio")]
    return {
        "today": len(items),
        "by_source": by_source,
        "avg_answer_s": round(sum(times) / len(times), 2) if times else None,
        "german": sum(1 for e in items if e.get("lang") == "de"),
    }


def _emit(event: dict) -> None:
    if broadcaster is not None:
        try:
            broadcaster(event)
        except Exception:
            pass
