"""
Visitor questions -> better answers.

  * questions(): what visitors ask most (app + G1 microphone + Studio tests), grouped by
    normalised text, with the latest answer and a "weak" flag when G1 had to say it
    does not know (those are the gaps to fill in the knowledge base or with a fixed card).
  * knowledge: the lab facts the AI may use (app/data/knowledge_base.json), editable in
    Studio. Each entry: title, keywords, facts. match() shows which entries a question hits.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

from app.services import interaction_control, knowledge_service

WEAK_PATTERNS = [
    r"\bi (do not|don't) know\b", r"\bnot sure\b", r"\bi (can't|cannot) (say|tell|answer|help)\b",
    r"\bno (verified |specific )?information\b", r"\bplease ask (a|the) (member|staff|lab)",
    r"\bsorry, that did not work\b", r"\bi have no (details|information)\b", r"\bunknown\b",
    r"\bweiß (ich )?(das )?nicht\b", r"\bkeine (genauen |verifizierten )?informationen\b",
    r"\bleider\b.*\b(nicht|keine)\b", r"\bdas ging nicht\b", r"\bfragen sie (bitte )?(das|einen|eine)\b",
]
_weak_re = re.compile("|".join(WEAK_PATTERNS), re.IGNORECASE)
MAX_ENTRIES = 200
_lock = threading.Lock()


def is_weak(reply: str) -> bool:
    return bool(_weak_re.search(reply or ""))


def _norm(text: str) -> str:
    t = re.sub(r"[^\wäöüß ]+", " ", (text or "").lower())
    t = re.sub(r"^(hey|hi|hallo|hello|ok|okay) (g1|g one|gee one)\b", "", " ".join(t.split())).strip()
    return t


def _read_log(path: str | None = None) -> list[dict]:
    path = path or interaction_control.LOG_FILE
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def questions(days: int = 30, path: str | None = None) -> dict:
    since = (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%dT%H:%M:%S")
    groups: dict[str, dict] = {}
    for e in _read_log(path):
        if e.get("source") not in ("app", "mic", "studio") or e.get("t", "") < since:
            continue
        if e.get("note") == "paused":
            continue
        key = _norm(e.get("heard", ""))
        if len(key) < 3:
            continue
        g = groups.setdefault(key, {"question": e.get("heard", "").strip(), "count": 0, "sources": defaultdict(int),
                                    "langs": defaultdict(int), "last": "", "answer": "", "weak": 0, "seconds": []})
        g["count"] += 1
        g["sources"][e["source"]] += 1
        g["langs"][e.get("lang", "en")] += 1
        if e.get("t", "") >= g["last"]:
            g["last"], g["answer"], g["question"] = e.get("t", ""), e.get("reply", ""), e.get("heard", "").strip()
        if is_weak(e.get("reply", "")):
            g["weak"] += 1
        if e.get("seconds") is not None:
            g["seconds"].append(e["seconds"])
    items = []
    for g in groups.values():
        s = g.pop("seconds")
        g["avg_s"] = round(sum(s) / len(s), 2) if s else None
        g["sources"], g["langs"] = dict(g["sources"]), dict(g["langs"])
        g["weak_last"] = is_weak(g["answer"])
        items.append(g)
    items.sort(key=lambda g: g["last"], reverse=True)
    items.sort(key=lambda g: g["count"], reverse=True)          # most asked first, newest first on ties
    weak = [g for g in items if g["weak_last"]]
    total = sum(g["count"] for g in items)
    return {"days": days, "total": total, "distinct": len(items), "weak_count": len(weak),
            "top": items[:100], "weak": sorted(weak, key=lambda g: g["last"], reverse=True)[:100]}


# ---------------------------------------------------------------- knowledge base editing
def load_knowledge() -> list[dict]:
    try:
        data = json.loads(knowledge_service.KNOWLEDGE_PATH.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    except (OSError, ValueError):
        return []


def _clean_entry(e: dict, seen: set) -> dict:
    title = " ".join(str(e.get("title", "")).split())[:80]
    facts = " ".join(str(e.get("facts", "")).split())
    if not title or not facts:
        raise ValueError("Every entry needs a title and facts")
    if len(facts) > 1500:
        raise ValueError(f"Facts too long (max 1500): {title}")
    kws = e.get("keywords", [])
    if isinstance(kws, str):
        kws = kws.split(",")
    keywords = []
    for k in kws:
        k = " ".join(str(k).lower().split())[:40]
        if k and k not in keywords:
            keywords.append(k)
    if not keywords:
        keywords = [w for w in re.findall(r"\w+", title.lower()) if len(w) > 2][:5]
    eid = re.sub(r"[^a-z0-9_-]", "", str(e.get("id", "")).lower())[:40] or re.sub(r"[^a-z0-9]+", "_", title.lower())[:40]
    base, n = eid, 2
    while eid in seen:
        eid, n = f"{base}_{n}", n + 1
    seen.add(eid)
    return {"id": eid, "title": title, "keywords": keywords[:30], "facts": facts}


def save_knowledge(entries: list) -> list[dict]:
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError(f"entries must be a list (max {MAX_ENTRIES})")
    seen: set = set()
    clean = [_clean_entry(e, seen) for e in entries if isinstance(e, dict)]
    path = knowledge_service.KNOWLEDGE_PATH
    with _lock:
        if path.exists():                          # keep one backup of the previous version
            bak = path.with_suffix(".json.bak")
            try:
                bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "entries": clean},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return clean


def match(question: str) -> list[dict]:
    try:
        return knowledge_service.retrieve_knowledge(question)
    except RuntimeError:
        return []
