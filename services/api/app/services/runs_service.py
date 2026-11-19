"""
Run log for G1 Studio -> Evaluation.

The guide service on the robot appends one JSON line per guide / tour run to
hfu_nav/runs/runs.jsonl. Studio reads it, adds notes / "exclude" flags (kept in
Studio's own data folder, the robot file is never changed) and computes the
statistics for the thesis evaluation chapter.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
import threading

from app.services.lab_map_service import _DATA, apply_pose, lab_map

RUNS_FILE = os.path.expanduser(os.getenv(
    "G1_RUNS_FILE", "~/Documents/Projekte/g1pilot-main/hfu_nav/runs/runs.jsonl"))
META_FILE = os.path.expanduser(os.getenv("G1_RUNS_META_FILE", os.path.join(_DATA, "runs_meta.json")))

_lock = threading.Lock()


def _meta() -> dict:
    try:
        with open(META_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_runs(path: str = RUNS_FILE) -> list[dict]:
    runs = []
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                r["id"] = f"{i}-{r.get('started', '')}"
                runs.append(r)
    except OSError:
        pass
    meta = _meta()
    for r in runs:
        m = meta.get(r["id"], {})
        r["note"] = m.get("note", "")
        r["excluded"] = bool(m.get("excluded", False))
    return runs


def set_meta(run_id: str, note: str | None, excluded: bool | None) -> dict:
    with _lock:
        meta = _meta()
        m = meta.setdefault(run_id, {})
        if note is not None:
            m["note"] = str(note)[:300]
        if excluded is not None:
            m["excluded"] = bool(excluded)
        os.makedirs(os.path.dirname(META_FILE), exist_ok=True)
        tmp = META_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(meta, f, indent=1)
        os.replace(tmp, META_FILE)
        return m


def _route_transform(route: str):
    al = lab_map.alignment()
    r = al.get("routes", {}).get(route)
    if r and r.get("ok"):
        return (r["tx"], r["ty"], r["theta"])
    h = al.get("home")
    return (h["x"], h["y"], h["yaw"]) if h else None


def with_map_positions(runs: list[dict]) -> list[dict]:
    cache: dict = {}
    for r in runs:
        name = r.get("route", "")
        if name not in cache:
            cache[name] = _route_transform(name)
        T = cache[name]
        r["blocked_map"] = ([list(apply_pose(T, (p[0], p[1], 0.0))[:2]) for p in r.get("blocked_at", [])]
                            if T else [])
    return runs


def _mean(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else None


def stats(runs: list[dict]) -> dict:
    use = [r for r in runs if not r.get("excluded")]
    finished = [r for r in use if r.get("result") != "cancelled"]
    done = [r for r in use if r.get("result") == "done"]
    al = [r.get("alignment") or {} for r in use if (r.get("alignment") or {}).get("used")]
    per_route: dict = {}
    for r in use:
        d = per_route.setdefault(r.get("route", "?"), {"runs": 0, "done": 0, "durations": [], "blocked_s": []})
        d["runs"] += 1
        d["done"] += r.get("result") == "done"
        if r.get("result") == "done":
            d["durations"].append(r.get("duration_s"))
        d["blocked_s"].append(r.get("blocked_s", 0))
    return {
        "runs": len(use),
        "excluded": len(runs) - len(use),
        "done": len(done),
        "aborted": sum(r.get("result") == "aborted" for r in use),
        "cancelled": sum(r.get("result") == "cancelled" for r in use),
        "success_rate": round(len(done) / len(finished), 3) if finished else None,
        "avg_duration_s": _mean([r.get("duration_s") for r in done]),
        "avg_blocked_s": _mean([r.get("blocked_s", 0) for r in use]),
        "total_distance_m": round(sum((r.get("length_m") or 0) * (2 if r.get("return_home") and r.get("kind") == "route"
                                                                   else 1) * (r.get("progress") or 0)
                                      for r in use), 1),
        "alignment": {
            "runs": len(al),
            "avg_shift_cm": _mean([math.hypot(a.get("dx", 0), a.get("dy", 0)) * 100 for a in al]),
            "max_shift_cm": round(max((math.hypot(a.get("dx", 0), a.get("dy", 0)) * 100 for a in al), default=0), 1)
            if al else None,
            "avg_abs_yaw_deg": _mean([abs(a.get("dyaw_deg", 0)) for a in al]),
            "avg_fit": _mean([a.get("fit") for a in al]),
        },
        "per_route": {k: {"runs": v["runs"], "done": v["done"],
                          "success_rate": round(v["done"] / v["runs"], 3) if v["runs"] else None,
                          "avg_duration_s": _mean(v["durations"]), "avg_blocked_s": _mean(v["blocked_s"])}
                      for k, v in per_route.items()},
    }


CSV_FIELDS = ["started", "route", "kind", "lang", "result", "duration_s", "length_m", "stops", "progress",
              "blocked_count", "blocked_s", "align_dx_m", "align_dy_m", "align_dyaw_deg", "align_fit",
              "message", "note", "excluded"]


def to_csv(runs: list[dict]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in runs:
        a = r.get("alignment") or {}
        w.writerow({**r, "align_dx_m": a.get("dx"), "align_dy_m": a.get("dy"),
                    "align_dyaw_deg": a.get("dyaw_deg"), "align_fit": a.get("fit")})
    return out.getvalue()
