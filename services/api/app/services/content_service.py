"""Content helpers for the Studio tour editor: local AI translation + say on G1."""
from __future__ import annotations

import json
import os
import re
import urllib.request

from app.services import robot_hub

TRANSLATE_MODEL = os.getenv("G1_TRANSLATE_MODEL", "qwen3:4b")
LANG_NAME = {"en": "English", "de": "German"}


def translate(text: str, source: str, target: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if source not in LANG_NAME or target not in LANG_NAME:
        raise ValueError("Languages must be 'en' or 'de'.")
    prompt = (
        f"/no_think\nTranslate the following {LANG_NAME[source]} text into natural, friendly "
        f"spoken {LANG_NAME[target]} for a robot guide in a university lab. Keep names of machines "
        f"and companies unchanged. Output ONLY the translation, no quotes, no explanation.\n\n{text}"
    )
    body = json.dumps({"model": TRANSLATE_MODEL, "prompt": prompt, "stream": False,
                       "keep_alive": "30m", "options": {"temperature": 0.2}}).encode()
    req = urllib.request.Request(f"{robot_hub.OLLAMA}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read()).get("response", "")
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip().strip('"').strip()
    return out


def say_on_g1(text: str, lang: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to say.")
    code, body = robot_hub.post_json(f"{robot_hub.VOICE}/speak",
                                     {"text": text[:600], "lang": lang if lang in LANG_NAME else "en"},
                                     timeout=10)
    if code >= 400:
        raise RuntimeError((body or {}).get("detail", f"voice bridge HTTP {code}"))
    return body or {}
