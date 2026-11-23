"""
Evaluation recorder - one summary over everything G1 did, for the thesis evaluation chapter.

Sources (all written automatically while G1 is used):
  conversations   data/interaction_log.jsonl                     (app, G1 microphone, Studio)
  walks           hfu_nav/runs/runs.jsonl (robot) via runs_service + data/trajectories/*.json
  point demo      hfu_pick/logs/point_runs.jsonl (robot PC)
  shows           data/show_runs.jsonl
Each part: counts, success rates, timings, per-day activity; every part exports as CSV.
"""
from __future__ import annotations

import csv
import io
import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.services import activity_service, insights_service, interaction_control, runs_service, show_service

POINT_RUNS_FILE = os.path.expanduser(os.getenv(
    "G1_POINT_RUNS_FILE", "~/Documents/Projekte/g1pilot-main/hfu_pick/logs/point_runs.jsonl"))


def _jsonl(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def _since(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S") if days else ""


def _stat(values) -> dict:
    v = sorted(x for x in values if isinstance(x, (int, float)))
    if not v:
        return {"n": 0, "mean": None, "median": None, "p90": None, "min": None, "max": None}
    return {"n": len(v), "mean": round(statistics.mean(v), 2), "median": round(statistics.median(v), 2),
            "p90": round(v[min(len(v) - 1, int(0.9 * len(v)))], 2), "min": round(v[0], 2), "max": round(v[-1], 2)}


def _rate(ok: int, n: int):
    return round(ok / n, 3) if n else None


def conversations(days: int = 0) -> dict:
    since = _since(days)
    rows = [e for e in _jsonl(interaction_control.LOG_FILE) if e.get("t", "") >= since]
    asked = [e for e in rows if e.get("source") in ("app", "mic", "studio") and e.get("note") != "paused"]
    by_src = {s: [e for e in asked if e["source"] == s] for s in ("app", "mic", "studio")}
    weak = sum(1 for e in asked if insights_service.is_weak(e.get("reply", "")))
    return {
        "total": len(asked),
        "operator_sentences": sum(1 for e in rows if e.get("source") == "operator"),
        "paused_refusals": sum(1 for e in rows if e.get("note") == "paused"),
        "by_source": {s: len(v) for s, v in by_src.items()},
        "by_language": dict(Counter(e.get("lang", "en") for e in asked)),
        "answer_s": {s: _stat(e.get("seconds") for e in v) for s, v in by_src.items()},
        "answer_s_all": _stat(e.get("seconds") for e in asked),
        "weak_answers": weak,
        "weak_rate": _rate(weak, len(asked)),
    }


def walks(days: int = 0) -> dict:
    since = _since(days)
    runs = [r for r in runs_service.load_runs() if r.get("started", "") >= since]
    s = runs_service.stats(runs)
    goto = [r for r in runs if r.get("kind") == "goto" or str(r.get("route", "")).startswith("goto:")]
    tr = [t for t in activity_service.list_trajectories() if (t.get("started") or "") >= since]
    return {**s, "autonomous_goto": {"runs": len(goto), "done": sum(r.get("result") == "done" for r in goto),
                                     "success_rate": _rate(sum(r.get("result") == "done" for r in goto),
                                                           sum(r.get("result") != "cancelled" for r in goto))},
            "recorded_paths": len(tr), "recorded_m": round(sum(t.get("length_m") or 0 for t in tr), 1),
            "blocked_events": sum(t.get("blocked") or 0 for t in tr)}


def points(days: int = 0) -> dict:
    since = _since(days)
    rows = [r for r in _jsonl(POINT_RUNS_FILE) if str(r.get("started", r.get("t", ""))) >= since]
    done = [r for r in rows if r.get("result") == "done"]
    by_target = defaultdict(lambda: {"runs": 0, "done": 0})
    for r in rows:
        d = by_target[r.get("target", "?")]
        d["runs"] += 1
        d["done"] += r.get("result") == "done"
    return {"runs": len(rows), "done": len(done), "success_rate": _rate(len(done), len(rows)),
            "results": dict(Counter(r.get("result", "?") for r in rows)),
            "duration_s": _stat(r.get("duration_s") for r in done), "by_target": dict(by_target),
            "by_side": dict(Counter(r.get("side") or "?" for r in rows))}


def shows(days: int = 0) -> dict:
    since = _since(days)
    rows = [r for r in show_service.load_runs() if (r.get("started") or "") >= since]
    failed_types = Counter()
    for r in rows:
        for e in r.get("log", []):
            if e.get("result") == "failed":
                failed_types[e.get("type", "?")] += 1
    step_s = defaultdict(list)
    for r in rows:
        for e in r.get("log", []):
            if e.get("result") == "done":
                step_s[e.get("type", "?")].append(e.get("seconds"))
    done = sum(r.get("result") == "done" for r in rows)
    finished = sum(r.get("result") != "stopped" for r in rows)
    return {"runs": len(rows), "done": done, "stopped": sum(r.get("result") == "stopped" for r in rows),
            "failed": sum(r.get("result") == "failed" for r in rows), "success_rate": _rate(done, finished),
            "duration_s": _stat(r.get("duration_s") for r in rows if r.get("result") == "done"),
            "failed_step_types": dict(failed_types),
            "step_seconds": {k: _stat(v) for k, v in step_s.items()}}


def daily(days: int = 14) -> list[dict]:
    """Activity per day (for the bar chart): conversations, walks, point runs, shows."""
    days = max(1, min(days or 14, 90))
    start = (datetime.now() - timedelta(days=days - 1)).date()
    table = {(start + timedelta(days=i)).isoformat(): {"conversations": 0, "walks": 0, "points": 0, "shows": 0}
             for i in range(days)}

    def add(t, key):
        d = str(t or "")[:10]
        if d in table:
            table[d][key] += 1
    for e in _jsonl(interaction_control.LOG_FILE):
        if e.get("source") in ("app", "mic", "studio"):
            add(e.get("t"), "conversations")
    for r in runs_service.load_runs():
        add(r.get("started"), "walks")
    for r in _jsonl(POINT_RUNS_FILE):
        add(r.get("started", r.get("t")), "points")
    for r in show_service.load_runs():
        add(r.get("started"), "shows")
    return [{"day": k, **v} for k, v in table.items()]


def summary(days: int = 0) -> dict:
    return {"days": days, "conversations": conversations(days), "walks": walks(days), "points": points(days),
            "shows": shows(days), "daily": daily(max(days, 14))}


# ---------------------------------------------------------------- CSV
def _csv(rows: list[dict], fields: list[str]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    return out.getvalue()


def export(kind: str) -> str:
    if kind == "conversations":
        rows = _jsonl(interaction_control.LOG_FILE)
        for r in rows:
            r["weak"] = insights_service.is_weak(r.get("reply", ""))
        return _csv(rows, ["id", "t", "source", "lang", "heard", "reply", "seconds", "spoke", "weak", "note"])
    if kind == "points":
        rows = _jsonl(POINT_RUNS_FILE)
        fields = sorted({k for r in rows for k in r} - {"log"}) or ["started", "target", "result"]
        return _csv(rows, fields)
    if kind == "shows":
        return _csv(show_service.load_runs(), ["started", "show", "title", "lang", "mode", "result", "duration_s",
                                               "steps_total", "steps_done", "failed_step", "message"])
    if kind == "paths":
        return _csv(activity_service.list_trajectories(limit=10000),
                    ["id", "started", "route", "kind", "result", "duration_s", "length_m", "blocked", "points"])
    raise KeyError(kind)
