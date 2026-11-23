"""
Speaking cards - the "Try asking" buttons on the G1 Remote Talk screen, managed in G1 Studio.

The lab team picks from a big library (and adds its own) on Studio -> Interaction. The cards that
are switched on are pushed live to every app (WebSocket {"type": "talk_cards_changed"}); the app
reloads GET /api/interaction/cards/app. A visitor taps a card -> the text is asked like a spoken
question.

A card can have a fixed answer: then G1 says exactly that (no AI, instant, always the same) -
good for the important demo sentences. Without one, the local AI answers as usual.

Stored in services/api/data/talk_cards.json (list order = order in the app).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
CARDS_FILE = os.path.expanduser(os.getenv("G1_TALK_CARDS_FILE", os.path.join(_DATA, "talk_cards.json")))

MAX_CARDS = 300
MAX_IN_APP = 40
TEXT_MAX = 120
ANSWER_MAX = 400
CATEGORY_MAX = 30


def _c(cid, cat, en, de, on=False, a_en="", a_de=""):
    return {"id": cid, "category": cat, "en": en, "de": de, "answer_en": a_en, "answer_de": a_de,
            "enabled": on, "builtin": True}


# The built-in library. Fixed answers only where the facts are certain; everything else -> AI.
LIBRARY = [
    # ---- About G1
    _c("who", "About G1", "Who are you?", "Wer bist du?", True,
       "I'm G1, a humanoid robot made by Unitree. Here at Furtwangen University I welcome visitors, "
       "guide them through the lab and show what robots can do.",
       "Ich bin G1, ein humanoider Roboter von Unitree. Hier an der Hochschule Furtwangen begrüße ich "
       "Besucher, führe sie durch das Labor und zeige, was Roboter können."),
    _c("what_can", "About G1", "What can you do?", "Was kannst du?", True),
    _c("name", "About G1", "What is your name?", "Wie heißt du?", False,
       "My name is G1.", "Ich heiße G1."),
    _c("maker", "About G1", "Who built you?", "Wer hat dich gebaut?"),
    _c("how_tall", "About G1", "How tall are you?", "Wie groß bist du?"),
    _c("how_heavy", "About G1", "How heavy are you?", "Wie schwer bist du?"),
    _c("battery", "About G1", "How long does your battery last?", "Wie lange hält dein Akku?"),
    _c("sensors", "About G1", "How do you see the world?", "Wie siehst du die Welt?"),
    _c("lidar", "About G1", "What is a LiDAR?", "Was ist ein LiDAR?"),
    _c("brain", "About G1", "What computer is your brain?", "Welcher Computer ist dein Gehirn?"),
    _c("ai", "About G1", "How do you understand me?", "Wie verstehst du mich?"),
    _c("languages", "About G1", "Which languages do you speak?", "Welche Sprachen sprichst du?", False,
       "I speak English and German. Just talk to me in the language you like.",
       "Ich spreche Deutsch und Englisch. Sprechen Sie einfach in Ihrer Sprache mit mir."),
    _c("feel", "About G1", "Do you have feelings?", "Hast du Gefühle?"),
    _c("learn", "About G1", "Can you learn new things?", "Kannst du Neues lernen?"),
    _c("walk_how", "About G1", "How do you keep your balance?", "Wie hältst du das Gleichgewicht?"),
    # ---- Lab & HFU
    _c("lab", "Lab & HFU", "What do you do in this lab?", "Was macht ihr in diesem Labor?", True),
    _c("hfu", "Lab & HFU", "What is Furtwangen University?", "Was ist die Hochschule Furtwangen?"),
    _c("ipse", "Lab & HFU", "What is IPSE?", "Was ist das IPSE?"),
    _c("thesis", "Lab & HFU", "What is your thesis project about?", "Worum geht es in deinem Masterprojekt?"),
    _c("study", "Lab & HFU", "Can I study robotics here?", "Kann ich hier Robotik studieren?"),
    _c("machines", "Lab & HFU", "Which machines are in this lab?", "Welche Maschinen gibt es hier?"),
    _c("printer", "Lab & HFU", "What is the 3D printer used for?", "Wofür wird der 3D-Drucker benutzt?"),
    _c("other_robots", "Lab & HFU", "Which other robots are here?", "Welche anderen Roboter gibt es hier?"),
    _c("safety", "Lab & HFU", "What are the safety rules here?", "Welche Sicherheitsregeln gelten hier?"),
    # ---- Demos (the app turns these into real actions)
    _c("wave", "Demos", "Can you wave?", "Kannst du winken?", True),
    _c("hand", "Demos", "Shake my hand", "Gib mir die Hand", True),
    _c("see", "Demos", "What do you see?", "Was siehst du?", True),
    _c("bottle", "Demos", "Find a bottle", "Finde eine Flasche"),
    _c("tour", "Demos", "Give me a lab tour", "Zeig mir das Labor"),
    _c("point", "Demos", "Show me the pick and place demo", "Zeig mir die Greif-Demo"),
    # ---- Robotics
    _c("humanoid", "Robotics", "What is a humanoid robot?", "Was ist ein humanoider Roboter?"),
    _c("why_legs", "Robotics", "Why do robots need legs?", "Warum brauchen Roboter Beine?"),
    _c("slam", "Robotics", "How do you find your way?", "Wie findest du deinen Weg?"),
    _c("future", "Robotics", "Will robots work in our homes?", "Werden Roboter bei uns zu Hause arbeiten?"),
    _c("jobs", "Robotics", "Will robots take our jobs?", "Nehmen Roboter uns die Arbeit weg?"),
    _c("cobot", "Robotics", "What is a collaborative robot?", "Was ist ein kollaborativer Roboter?"),
    _c("industry", "Robotics", "Where are robots used in industry?", "Wo werden Roboter in der Industrie eingesetzt?"),
    # ---- Fun
    _c("joke", "Fun", "Tell me a joke", "Erzähl mir einen Witz"),
    _c("dance", "Fun", "Can you dance?", "Kannst du tanzen?"),
    _c("food", "Fun", "What is your favourite food?", "Was isst du am liebsten?"),
    _c("age", "Fun", "How old are you?", "Wie alt bist du?"),
    _c("friend", "Fun", "Do you have friends?", "Hast du Freunde?"),
    _c("dream", "Fun", "What do you dream about?", "Wovon träumst du?"),
    _c("fact", "Fun", "Tell me a fun robot fact", "Erzähl mir etwas Lustiges über Roboter"),
    # ---- Visit
    _c("hello", "Visit", "Hello G1!", "Hallo G1!"),
    _c("first_time", "Visit", "It's my first time here", "Ich bin zum ersten Mal hier"),
    _c("contact", "Visit", "Who can I talk to in the lab?", "Mit wem kann ich im Labor sprechen?"),
    _c("bye", "Visit", "Goodbye G1", "Tschüss G1", False,
       "Goodbye, it was nice talking to you. Enjoy the rest of your visit!",
       "Auf Wiedersehen, es war schön, mit Ihnen zu sprechen. Genießen Sie den restlichen Besuch!"),
]

_lock = threading.Lock()
broadcaster = None   # set in main.py


def _norm(text: str) -> str:
    return re.sub(r"[^\wäöüß ]+", "", " ".join((text or "").lower().split())).strip()


def _clean(card: dict, seen: set) -> dict:
    en = " ".join(str(card.get("en", "")).split())
    if not en:
        raise ValueError("Every card needs an English text")
    de = " ".join(str(card.get("de", "")).split()) or en
    if len(en) > TEXT_MAX or len(de) > TEXT_MAX:
        raise ValueError(f"Card text too long (max {TEXT_MAX}): {en[:40]}…")
    a_en = " ".join(str(card.get("answer_en", "") or "").split())
    a_de = " ".join(str(card.get("answer_de", "") or "").split())
    if len(a_en) > ANSWER_MAX or len(a_de) > ANSWER_MAX:
        raise ValueError(f"Fixed answer too long (max {ANSWER_MAX}): {en[:40]}…")
    cid = re.sub(r"[^a-z0-9_-]", "", str(card.get("id", "")).lower())[:40]
    if not cid or cid in seen:
        cid = f"c{int(time.time() * 1000) % 10**9}_{len(seen)}"
    seen.add(cid)
    builtin_ids = {c["id"] for c in LIBRARY}
    return {
        "id": cid,
        "category": (" ".join(str(card.get("category", "") or "").split()) or "My cards")[:CATEGORY_MAX],
        "en": en, "de": de, "answer_en": a_en, "answer_de": a_de,
        "enabled": bool(card.get("enabled")),
        "builtin": cid in builtin_ids and bool(card.get("builtin", True)),
    }


def load() -> dict:
    data = None
    try:
        with open(CARDS_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        return {"version": 0, "updated": "", "cards": [dict(c) for c in LIBRARY]}
    cards = data["cards"]
    have = {c.get("id") for c in cards}
    cards += [dict(c, enabled=False) for c in LIBRARY if c["id"] not in have]   # new built-ins, off
    return {"version": int(data.get("version", 0)), "updated": data.get("updated", ""), "cards": cards}


def save(cards: list) -> dict:
    if not isinstance(cards, list):
        raise ValueError("cards must be a list")
    if len(cards) > MAX_CARDS:
        raise ValueError(f"Too many cards (max {MAX_CARDS})")
    seen: set = set()
    clean = [_clean(c, seen) for c in cards if isinstance(c, dict)]
    on = sum(1 for c in clean if c["enabled"])
    if on > MAX_IN_APP:
        raise ValueError(f"Max {MAX_IN_APP} cards can be shown in the app at once ({on} selected)")
    with _lock:
        version = load()["version"] + 1
        out = {"version": version, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "cards": clean}
        os.makedirs(os.path.dirname(CARDS_FILE), exist_ok=True)
        tmp = CARDS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CARDS_FILE)
    if broadcaster is not None:
        try:
            broadcaster({"type": "talk_cards_changed", "data": {"version": version, "in_app": on}})
        except Exception:
            pass
    return out


def app_cards() -> dict:
    d = load()
    return {"version": d["version"],
            "cards": [{"id": c["id"], "category": c.get("category", ""), "en": c["en"], "de": c.get("de") or c["en"]}
                      for c in d["cards"] if c.get("enabled")]}


def fixed_answer(question: str, language: str | None = None) -> tuple[str, str] | None:
    """(answer, lang) if the question is exactly a switched-on card with a fixed answer."""
    q = _norm(question)
    if not q:
        return None
    for c in load()["cards"]:
        if not c.get("enabled"):
            continue
        if q == _norm(c.get("de", "")) and (c.get("answer_de") or c.get("answer_en")):
            return (c.get("answer_de") or c["answer_en"]), ("de" if c.get("answer_de") else "en")
        if q == _norm(c.get("en", "")) and (c.get("answer_en") or c.get("answer_de")):
            if language == "de" and c.get("answer_de"):
                return c["answer_de"], "de"
            return (c.get("answer_en") or c["answer_de"]), ("en" if c.get("answer_en") else "de")
    return None
