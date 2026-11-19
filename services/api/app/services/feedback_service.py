"""
Visitor feedback from the G1 Remote app (after a tour, or any time).

Stored as JSON lines in services/api/data/feedback.jsonl (anonymous: no names,
no device IDs). Includes the standard System Usability Scale (SUS, 10 items,
score 0-100) for the thesis evaluation.
"""
from __future__ import annotations

import csv
import io
import json
import os
import statistics
import threading
import time

from app.services.lab_map_service import _DATA

FEEDBACK_FILE = os.path.expanduser(os.getenv("G1_FEEDBACK_FILE", os.path.join(_DATA, "feedback.jsonl")))
_lock = threading.Lock()
_last_submit: list[float] = []


def sus_score(answers: list[int]) -> float | None:
    """Standard SUS: odd items (score-1), even items (5-score), sum x 2.5."""
    if len(answers) != 10 or any(a not in (1, 2, 3, 4, 5) for a in answers):
        return None
    total = sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers))
    return total * 2.5


def validate(body: dict) -> dict:
    rating = body.get("rating")
    if rating is not None and rating not in (1, 2, 3, 4, 5):
        raise ValueError("rating must be 1-5")
    rec = body.get("recommend")
    if rec is not None and rec not in ("yes", "maybe", "no"):
        raise ValueError("recommend must be yes / maybe / no")
    sus = body.get("sus")
    if sus is not None and sus_score(sus) is None:
        raise ValueError("sus must be 10 answers of 1-5")
    if rating is None and rec is None and sus is None and not body.get("comment"):
        raise ValueError("empty feedback")
    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "lang": body.get("lang") if body.get("lang") in ("en", "de") else "en",
        "context": str(body.get("context") or "general")[:40],      # e.g. "tour:lab_tour"
        "rating": rating, "recommend": rec, "sus": sus,
        "sus_score": sus_score(sus) if sus else None,
        "comment": str(body.get("comment") or "").strip()[:500],
    }


def submit(body: dict) -> dict:
    now = time.monotonic()
    with _lock:
        _last_submit[:] = [t for t in _last_submit if now - t < 60]
        if len(_last_submit) >= 20:
            raise RuntimeError("Too much feedback in one minute.")
        _last_submit.append(now)
        rec = validate(body)
        os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load() -> list[dict]:
    out = []
    try:
        with open(FEEDBACK_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def stats(items: list[dict]) -> dict:
    ratings = [i["rating"] for i in items if i.get("rating")]
    sus = [i["sus_score"] for i in items if i.get("sus_score") is not None]
    rec = [i["recommend"] for i in items if i.get("recommend")]
    return {
        "count": len(items),
        "avg_rating": round(statistics.mean(ratings), 2) if ratings else None,
        "ratings": {str(k): ratings.count(k) for k in range(1, 6)},
        "sus_count": len(sus),
        "sus_mean": round(statistics.mean(sus), 1) if sus else None,
        "sus_sd": round(statistics.stdev(sus), 1) if len(sus) > 1 else None,
        "recommend_yes_pct": round(100 * rec.count("yes") / len(rec)) if rec else None,
        "recommend": {k: rec.count(k) for k in ("yes", "maybe", "no")},
    }


def to_csv(items: list[dict]) -> str:
    out = io.StringIO()
    fields = ["time", "lang", "context", "rating", "recommend", "sus_score"] + \
             [f"sus_{k}" for k in range(1, 11)] + ["comment"]
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for i in items:
        row = dict(i)
        for k, a in enumerate(i.get("sus") or [], start=1):
            row[f"sus_{k}"] = a
        w.writerow(row)
    return out.getvalue()
