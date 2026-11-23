"""
"What is G1 doing?" - live activity feed + walk recorder.

A background loop (every 0.5 s) looks at the robot services Studio already talks to
(guide / autonomous walking, map localizer pose, point demo, show runner) and turns state
changes into readable events ("Walking to Printer", "Path blocked - waiting", "Arrived").
Conversations are added by interaction_control (heard -> answered).

While G1 walks (guide / tour / goto) the pose is sampled into a trajectory; when the walk
ends it is saved to data/trajectories/<start>.json for Replay and the Evaluation chapter.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import deque

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
TRAJ_DIR = os.path.expanduser(os.getenv("G1_TRAJ_DIR", os.path.join(_DATA, "trajectories")))

ACTIVE = ("starting", "planning", "walking", "guiding", "blocked", "returning", "turning", "aligning",
          "replanning", "waiting", "speaking", "arrived")
DONE = ("done", "aborted", "cancelled", "failed", "error", "idle")
MIN_STEP_M = 0.05

_lock = threading.Lock()
_events: deque = deque(maxlen=200)
_seq = 0
broadcaster = None


def _emit(ev: dict) -> None:
    if broadcaster is not None:
        try:
            broadcaster(ev)
        except Exception:
            pass


def add_event(kind: str, text: str, detail: str = "", level: str = "info") -> dict:
    global _seq
    with _lock:
        _seq += 1
        e = {"id": _seq, "t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "text": text[:200],
             "detail": detail[:300], "level": level}
        _events.append(e)
    _emit({"type": "activity", "data": e})
    return e


def recent(limit: int = 80) -> list[dict]:
    with _lock:
        return list(_events)[-limit:]


def _valid_pose(pose: dict | None) -> dict | None:
    """Drop impossible poses (e.g. diverged odometry: x = -1.7e14) - the lab is < 100 m."""
    p = (pose or {}).get("pose") if pose else None
    try:
        if p and all(math.isfinite(float(p[k])) and abs(float(p[k])) < 500 for k in ("x", "y")):
            return pose
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _route_title(route: str | None) -> str:
    if not route:
        return ""
    r = re.sub(r"^goto:", "", route)
    return r.replace("_", " ")


class Tracker:
    """Pure state machine (no I/O) - fed with snapshots, emits events and trajectories."""

    def __init__(self, add=add_event, save=None, clock=time.time):
        self.add, self.clock = add, clock
        self.save = save or save_trajectory
        self.guide_state = None
        self.guide_msg = ""
        self.pick_state = None
        self.traj: dict | None = None
        self.now: dict = {}

    def feed(self, guide: dict | None, pose: dict | None, pick: dict | None, show: dict | None = None) -> None:
        guide, pick = guide or {}, pick or {}
        pose = _valid_pose(pose)
        gs, route = guide.get("state"), guide.get("route")
        title = guide.get("stop_title") or _route_title(route)
        # ---- walking
        if gs != self.guide_state and gs is not None:
            kind = guide.get("kind")
            if gs == "starting":
                what = "Starting tour" if kind == "tour" else "Walking to"
                self.add("walk", f"{what} {_route_title(route)}".strip())
            elif gs in ("walking", "guiding") and self.guide_state in ("blocked", "replanning"):
                self.add("walk", "Path free again – walking on")
            elif gs == "guiding" and guide.get("stop_title"):
                self.add("walk", f"Tour stop: {guide['stop_title']}")
            elif gs == "blocked":
                self.add("walk", "Path blocked – waiting", guide.get("message", ""), "warn")
            elif gs == "replanning":
                self.add("walk", "Planning a new way around the obstacle", "", "warn")
            elif gs == "arrived":
                self.add("walk", f"Arrived: {title}".strip(": "), "", "ok")
            elif gs == "returning":
                self.add("walk", "Walking back home")
            elif gs == "done" and self.guide_state in ACTIVE:
                self.add("walk", "Walk finished", guide.get("message", ""), "ok")
            elif gs in ("aborted", "cancelled") and self.guide_state in ACTIVE:
                self.add("walk", f"Walk {gs}", guide.get("message", ""), "warn")
        # ---- trajectory
        if gs in ACTIVE:
            if self.traj is None:
                self.traj = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": route, "kind": guide.get("kind"),
                             "samples": [], "blocked": [], "t0": self.clock()}
            p = (pose or {}).get("pose") if pose else None
            if p and p.get("x") is not None:
                s = self.traj["samples"]
                x, y = round(float(p["x"]), 3), round(float(p["y"]), 3)
                if not s or math.hypot(x - s[-1][1], y - s[-1][2]) >= MIN_STEP_M or gs != s[-1][4]:
                    s.append([round(self.clock() - self.traj["t0"], 1), x, y, round(float(p.get("yaw") or 0), 3), gs])
                if gs == "blocked" and self.guide_state != "blocked":
                    self.traj["blocked"].append([x, y])
        elif self.traj is not None and (gs in DONE or gs is None):
            tr, self.traj = self.traj, None
            tr["result"] = gs or "lost"
            tr["duration_s"] = round(self.clock() - tr.pop("t0"), 1)
            s = tr["samples"]
            tr["length_m"] = round(sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(s, s[1:])), 2)
            if len(s) >= 2:
                self.save(tr)
        self.guide_state = gs
        # ---- point demo
        ps = pick.get("state")
        if ps != self.pick_state and ps is not None:
            tgt = (pick.get("target") or "").replace("_", " ")
            if ps == "looking":
                self.add("arm", f"Looking for {tgt} on the table")
            elif ps == "moving":
                self.add("arm", f"Pointing at {tgt}", pick.get("message", ""))
            elif ps == "done" and self.pick_state not in (None, "idle", "talking"):
                self.add("arm", "Pointing done", pick.get("message", ""), "ok")
            elif ps in ("failed", "refused", "stopped") and self.pick_state is not None:
                self.add("arm", f"Point demo {ps}", pick.get("message", ""), "warn")
        self.pick_state = ps
        self.now = {
            "walk": {"state": gs, "route": _route_title(route), "progress": guide.get("progress"),
                     "message": guide.get("message", ""), "stop": guide.get("stop_title", "")} if gs else None,
            "pose": (pose or {}).get("pose") if pose else None,
            "arm": {"state": ps, "target": pick.get("target"), "message": pick.get("message", "")} if ps else None,
            "show": {k: show.get(k) for k in ("state", "title", "step", "steps", "label", "message")} if show else None,
        }

    def snapshot(self) -> dict:
        return {"now": self.now, "recording": self.traj is not None,
                "recording_points": len(self.traj["samples"]) if self.traj else 0}


def save_trajectory(tr: dict, folder: str | None = None) -> str:
    folder = folder or TRAJ_DIR
    os.makedirs(folder, exist_ok=True)
    name = re.sub(r"[^0-9T]", "", tr["started"]) + "_" + re.sub(r"[^a-zA-Z0-9_-]", "", str(tr.get("route") or "walk"))[:40]
    path = os.path.join(folder, name + ".json")
    with open(path, "w") as f:
        json.dump(tr, f)
    return name


def list_trajectories(folder: str | None = None, limit: int = 200) -> list[dict]:
    folder = folder or TRAJ_DIR
    out = []
    try:
        names = sorted((n for n in os.listdir(folder) if n.endswith(".json")), reverse=True)[:limit]
    except OSError:
        return []
    for n in names:
        try:
            with open(os.path.join(folder, n)) as f:
                tr = json.load(f)
            out.append({"id": n[:-5], "started": tr.get("started"), "route": _route_title(tr.get("route")),
                        "kind": tr.get("kind"), "result": tr.get("result"), "duration_s": tr.get("duration_s"),
                        "length_m": tr.get("length_m"), "blocked": len(tr.get("blocked", [])),
                        "points": len(tr.get("samples", []))})
        except (OSError, ValueError):
            continue
    return out


def get_trajectory(tid: str, folder: str | None = None) -> dict:
    if not re.fullmatch(r"[0-9T]+_[a-zA-Z0-9_-]*", tid or ""):
        raise KeyError(tid)
    with open(os.path.join(folder or TRAJ_DIR, tid + ".json")) as f:
        return json.load(f)


tracker = Tracker()


def poll_once() -> None:
    from app.services import robot_hub, show_service
    from app.services.lab_map_service import lab_map

    def safe(fn):
        try:
            return fn()
        except Exception:
            return None
    guide = safe(robot_hub.guide_status)
    gp = safe(robot_hub.guide_pose)
    lp = safe(robot_hub.loc_pose)
    pose = safe(lambda: lab_map.combine_live(gp, lp)) if (gp or lp) else None
    pick = safe(robot_hub.pick_status)
    show = show_service.runner.snapshot() if show_service.runner else None
    tracker.feed(guide, pose, pick, show)


async def run_forever() -> None:
    import asyncio
    from fastapi.concurrency import run_in_threadpool
    while True:
        try:
            await run_in_threadpool(poll_once)
        except Exception as exc:
            print(f"[activity] poll failed: {exc}")
        await asyncio.sleep(0.5)
