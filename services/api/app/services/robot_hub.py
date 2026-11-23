"""
Robot hub: G1 Studio talks to the robot-side services through here.

All robot services run on the same Jetson as this backend (host network), so
the defaults are 127.0.0.1. Override with G1_ROBOT_HOST or per-service env vars.
Nothing here moves the robot except stop/estop and starting a guide/tour, which
the guide service itself checks (FSM 500, joystick locked, no E-stop, HOME check).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HOST = os.getenv("G1_ROBOT_HOST", "127.0.0.1")


def _url(env: str, port: int) -> str:
    return os.getenv(env, f"http://{HOST}:{port}").rstrip("/")


TELEOP = _url("G1_TELEOP_URL", 8001)
GUIDE = _url("G1_GUIDE_URL", 8002)
VISION = _url("G1_VISION_URL", 8003)
VOICE = _url("G1_VOICE_URL", 8766)
STATUS_BRIDGE = _url("G1_STATUS_BRIDGE_URL", 8767)
CAMERA = _url("G1_CAMERA_URL", 8770)
TELEMETRY = _url("G1_TELEMETRY_URL", 8004)
LOCALIZER = _url("G1_LOCALIZER_URL", 8006)
PICK = _url("G1_PICK_URL", 8005)
OLLAMA = _url("G1_OLLAMA_URL", 11434)


class HubError(Exception):
    pass


def get_json(url: str, timeout: float = 1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read() or b"null")
        except Exception:
            raise HubError(f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise HubError(str(exc)) from exc


def post_json(url: str, payload: dict | None = None, timeout: float = 3.0) -> tuple[int, object]:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read() or b"null")
        except Exception:
            body = {"detail": f"HTTP {exc.code}"}
        return exc.code, body
    except Exception as exc:
        raise HubError(str(exc)) from exc


def get_bytes(url: str, timeout: float = 3.0) -> tuple[bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.HTTPError as exc:
        raise HubError(f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise HubError(str(exc)) from exc


# ---------------------------------------------------------------- health
def _probe(sid: str, name: str, port: int, url: str, check, required: bool = True) -> dict:
    t0 = time.monotonic()
    try:
        data = get_json(url, timeout=1.5)
        ok, detail = check(data)
    except HubError as exc:
        data, ok, detail = None, False, f"not reachable ({exc})"
    return {"id": sid, "name": name, "port": port, "ok": bool(ok), "detail": detail,
            "required": required, "ms": int((time.monotonic() - t0) * 1000), "data": data}


def _camera(d):
    ok = bool(d and d.get("camera_connected"))
    return ok, ("frames arriving" if ok else (d or {}).get("error") or "no frames")


def _teleop(d):
    fsm = (d or {}).get("fsm_id")
    return fsm is not None, (f"FSM {fsm}" if fsm is not None else "robot FSM not readable")


def _guide(d):
    return True, (d or {}).get("state", "?")


def _vision(d):
    return True, (d or {}).get("state", "ready")


def _voice(d):
    return True, "ready"


def _status_bridge(d):
    return True, "ready"


def _telemetry(d):
    b = (d or {}).get("battery") or {}
    if b.get("soc") is None:
        return False, "no battery data yet"
    return True, f"battery {b['soc']:.0f} %"


def _localizer(d):
    q = (d or {}).get("quality", "none")
    return q in ("good", "weak"), f"{q} · fit {d.get('fitness', 0):.2f}" if d else "no data"


def _pick(d):
    return True, (d or {}).get("state", "?")


def _ollama(d):
    models = [m.get("name") for m in (d or {}).get("models", [])]
    return bool(models), ", ".join(models[:4]) if models else "no models"


SERVICES = [
    ("teleop", "Teleop / joystick server", 8001, f"{TELEOP}/api/teleop/status", _teleop, True),
    ("guide", "Guide service (LiDAR guide + tours)", 8002, f"{GUIDE}/api/guide/status", _guide, False),
    ("camera", "Camera bridge", 8770, f"{CAMERA}/status", _camera, True),
    ("voice", "Voice bridge (Piper)", 8766, f"{VOICE}/status", _voice, True),
    ("status_bridge", "Status bridge", 8767, f"{STATUS_BRIDGE}/status", _status_bridge, False),
    ("ollama", "Local AI (Ollama)", 11434, f"{OLLAMA}/api/tags", _ollama, True),
    ("vision", "Vision service", 8003, f"{VISION}/api/vision/status", _vision, False),
    ("telemetry", "Telemetry (battery, motors)", 8004, f"{TELEMETRY}/api/telemetry", _telemetry, False),
    ("localizer", "Map localizer (G1 on the map)", 8006, f"{LOCALIZER}/api/loc/pose", _localizer, False),
    ("pick", "Point-at-it arm demo", 8005, f"{PICK}/api/pick/status", _pick, False),
]

_pool = ThreadPoolExecutor(max_workers=8)

FSM_NAMES = {0: "Zero torque", 1: "Damp", 2: "Squat", 3: "Sit", 4: "Stand up",
             200: "Start", 500: "Walking", 501: "Walking (alt)", 702: "Lie to stand",
             706: "Squat to stand", 801: "Run"}


def overview() -> dict:
    futures = [_pool.submit(_probe, *s) for s in SERVICES]
    services = [f.result() for f in futures]
    by_id = {s["id"]: s for s in services}
    t = by_id["teleop"]["data"] or {}
    robot = {
        "reachable": by_id["teleop"]["data"] is not None,
        "fsm_id": t.get("fsm_id"),
        "fsm_name": FSM_NAMES.get(t.get("fsm_id"), "unknown") if t.get("fsm_id") is not None else "unknown",
        "walking_mode": t.get("fsm_id") == 500,
        "estop": t.get("estop"),
        "estop_reason": t.get("estop_reason"),
        "teleop_active": t.get("teleop_active"),
        "operator": t.get("operator"),
        "state": t.get("state"),
        "gesture": t.get("gesture"),
        "stop_count": t.get("stop_count"),
        "limits": t.get("limits", {}),
    }
    guide = by_id["guide"]["data"]
    for s in services:
        s.pop("data", None)
    return {"time": time.time(), "services": services, "robot": robot, "guide": guide,
            "camera": {"ok": by_id["camera"]["ok"], "detail": by_id["camera"]["detail"]}}


# ---------------------------------------------------------------- robot actions
def stop() -> dict:
    return {"status": post_json(f"{TELEOP}/api/teleop/stop")[0],
            "guide": _safe(lambda: post_json(f"{GUIDE}/api/guide/cancel")[0])}


def estop() -> dict:
    code, body = post_json(f"{TELEOP}/api/teleop/estop")
    _safe(lambda: post_json(f"{GUIDE}/api/guide/cancel"))
    return {"status": code, "teleop": body}


def _safe(fn):
    try:
        return fn()
    except Exception as exc:
        return str(exc)


def routes():
    return get_json(f"{GUIDE}/api/guide/routes", timeout=3)


def guide_start(route: str, lang: str) -> tuple[int, object]:
    return post_json(f"{GUIDE}/api/guide/start", {"route": route, "lang": lang}, timeout=5)


def guide_cancel() -> tuple[int, object]:
    return post_json(f"{GUIDE}/api/guide/cancel", {}, timeout=3)


def guide_goto(body: dict) -> tuple[int, object]:
    return post_json(f"{GUIDE}/api/guide/goto", body, timeout=8)


def guide_plan(x: float, y: float) -> tuple[int, object]:
    return post_json(f"{GUIDE}/api/guide/plan", {"x": x, "y": y}, timeout=8)


def guide_nav():
    return get_json(f"{GUIDE}/api/guide/nav", timeout=1.5)


def guide_pose():
    return get_json(f"{GUIDE}/api/guide/pose", timeout=1.5)


# ---------------------------------------------------------------- map localizer (port 8006)
def loc_pose():
    return get_json(f"{LOCALIZER}/api/loc/pose", timeout=1.0)


def loc_status():
    return get_json(f"{LOCALIZER}/api/loc/status", timeout=1.5)


def loc_init(body: dict) -> tuple[int, object]:
    return post_json(f"{LOCALIZER}/api/loc/init", body, timeout=8)


def loc_relocalize() -> tuple[int, object]:
    return post_json(f"{LOCALIZER}/api/loc/relocalize", {}, timeout=30)


# ---------------------------------------------------------------- point-at-it demo (port 8005)
def pick_status():
    return get_json(f"{PICK}/api/pick/status", timeout=1.5)


def pick_scene():
    return get_json(f"{PICK}/api/pick/scene", timeout=6)


def pick_view() -> tuple[bytes, str]:
    return get_bytes(f"{PICK}/api/pick/view.jpg", timeout=3)


def pick_point(target: str, lang: str) -> tuple[int, object]:
    return post_json(f"{PICK}/api/pick/point", {"target": target, "lang": lang}, timeout=5)


def pick_stop() -> tuple[int, object]:
    return post_json(f"{PICK}/api/pick/stop", {}, timeout=3)


def camera_snapshot() -> tuple[bytes, str]:
    return get_bytes(f"{CAMERA}/snapshot", timeout=3)


# ---------------------------------------------------------------- G1 Vision (port 8003)
def vision_describe(question: str, lang: str) -> tuple[int, object]:
    return post_json(f"{VISION}/api/vision/describe", {"question": question, "lang": lang}, timeout=150)


def vision_find(obj: str, lang: str) -> tuple[int, object]:
    return post_json(f"{VISION}/api/vision/find", {"object": obj, "lang": lang}, timeout=5)


def vision_status():
    return get_json(f"{VISION}/api/vision/status", timeout=2)


def vision_cancel() -> tuple[int, object]:
    return post_json(f"{VISION}/api/vision/cancel", {}, timeout=3)


def vision_objects():
    return get_json(f"{VISION}/api/vision/objects", timeout=2)


def telemetry():
    return get_json(f"{TELEMETRY}/api/telemetry", timeout=2)


def telemetry_speed(since: float):
    return get_json(f"{TELEMETRY}/api/telemetry/speed?since={since:.3f}", timeout=2)


def guide_status():
    return get_json(f"{GUIDE}/api/guide/status", timeout=1.0)
