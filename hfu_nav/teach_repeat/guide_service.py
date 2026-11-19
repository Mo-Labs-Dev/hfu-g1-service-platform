#!/usr/bin/env python3
"""
G1 guide service - teach & repeat guiding for visitors.

Run INSIDE g1pilot-dev, with live FAST-LIO running (started on the home spot):
    G1_TELEOP_PIN=4821 ROS_DOMAIN_ID=1 \
      python3 /ros2_ws/src/g1pilot/hfu_nav/teach_repeat/guide_service.py

HTTP API (port 8002, reachable from the tablet):
    GET  /api/guide/routes                -> taught routes
    GET  /api/guide/status                -> current state / progress
    POST /api/guide/start  {"route": "coffee_machine", "lang": "en",
                            "return_home": true, "wait_s": 20}
                           a route with stops (e.g. "lab_tour") runs as a lab tour:
                           G1 stops, faces each exhibit and explains it
    POST /api/guide/cancel                -> stop now (robot stands still)

Motion goes through the teleop server (port 8001) like the app joystick, so
speed limits, dead-man, FSM-500 check and E-stop all apply. The app's STOP /
E-STOP buttons cancel a running guide.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guide_runner import GuideRunner  # noqa: E402
from route_core import FollowParams, Route, SafetyError, yaw_from_quaternion  # noqa: E402
from home_align import home_scan_path, load_home_scan  # noqa: E402

ROUTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "routes")


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 3.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


# ----------------------------------------------------------------------
# Motion: teleop server client (same protocol as the app)
# ----------------------------------------------------------------------

class TeleopMotion:
    def __init__(self, base: str, pin: str, operator: str = "G1 guide"):
        self.base = base.rstrip("/")
        self.pin = pin
        self.operator = operator
        self.token = None
        self.ws = None
        self._status: dict = {}
        self._stop_count0 = None
        self._lock = threading.Lock()

    def status(self) -> dict:
        with self._lock:
            if self.ws is not None and self._status:
                return dict(self._status)
        return http_json("GET", f"{self.base}/api/teleop/status")

    def begin(self) -> None:
        from websockets.sync.client import connect

        res = http_json("POST", f"{self.base}/api/teleop/unlock",
                        {"pin": self.pin, "operator": self.operator})
        self.token = res["token"]
        self._stop_count0 = res["status"].get("stop_count", 0)
        ws_url = self.base.replace("http://", "ws://") + f"/api/teleop/ws?token={self.token}"
        self.ws = connect(ws_url, open_timeout=3)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        try:
            for raw in self.ws:
                msg = json.loads(raw)
                if msg.get("type") == "status":
                    with self._lock:
                        self._status = msg
        except Exception:
            pass

    def send(self, x: float, yaw: float) -> None:
        if self.ws is None:
            return
        self.ws.send(json.dumps({"type": "cmd", "x": float(x), "y": 0.0,
                                 "yaw": float(yaw), "scale": 1.0}))

    def gesture(self, name: str) -> None:
        """Arm gesture with the same lease (e.g. "high_wave")."""
        if self.token:
            http_json("POST", f"{self.base}/api/teleop/gesture", {"token": self.token, "gesture": name})

    def stopped_by_operator(self) -> bool:
        with self._lock:
            count = self._status.get("stop_count")
        return (count is not None and self._stop_count0 is not None
                and count > self._stop_count0)

    def end(self) -> None:
        try:
            if self.ws is not None:
                self.ws.send(json.dumps({"type": "stop"}))
                self.ws.close()
        except Exception:
            pass
        self.ws = None
        if self.token:
            try:
                http_json("POST", f"{self.base}/api/teleop/lock", {"token": self.token})
            except Exception:
                pass
        self.token = None
        with self._lock:
            self._status = {}


class Voice:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def say(self, text: str, lang: str) -> None:
        return http_json("POST", f"{self.base}/speak", {"text": text, "lang": lang, "queue": True})

    def stop(self) -> None:
        http_json("POST", f"{self.base}/stop", {}, timeout=1.5)


# ----------------------------------------------------------------------
# Sensors: FAST-LIO odometry + current scan
# ----------------------------------------------------------------------

_PC2 = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}


def cloud_to_xyz(msg, max_points: int = 20000):
    """sensor_msgs/PointCloud2 -> Nx3 float array (or None)."""
    names = [f.name for f in msg.fields]
    if not {"x", "y", "z"} <= set(names):
        return None
    dt = np.dtype({"names": names, "formats": [_PC2[f.datatype] for f in msg.fields],
                   "offsets": [f.offset for f in msg.fields], "itemsize": msg.point_step})
    a = np.frombuffer(msg.data, dtype=dt, count=msg.width * msg.height)
    xyz = np.stack([a["x"], a["y"], a["z"]], axis=1).astype(np.float64)
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    if max_points and len(xyz) > max_points:
        xyz = xyz[:: len(xyz) // max_points + 1]
    return xyz


def load_route(path: str) -> Route:
    """Route + its HOME scan (if it was recorded with one) as route.home_xy."""
    route = Route.load(path)
    route.home_xy = load_home_scan(home_scan_path(path))
    return route


class RosSensors:
    def __init__(self, odom_topic: str, cloud_topic: str):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import PointCloud2

        rclpy.init()
        self.node = rclpy.create_node("g1_guide_service")
        self._pose = None
        self._points = None
        self._lock = threading.Lock()
        self.node.create_subscription(Odometry, odom_topic, self._on_odom, qos_profile_sensor_data)
        self.node.create_subscription(PointCloud2, cloud_topic, self._on_cloud, qos_profile_sensor_data)
        threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True).start()

    def _on_odom(self, msg) -> None:
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        with self._lock:
            self._pose = (time.monotonic(), p.x, p.y, p.z, yaw_from_quaternion(q.x, q.y, q.z, q.w))

    def _on_cloud(self, msg) -> None:
        xyz = cloud_to_xyz(msg)
        if xyz is None:
            return
        with self._lock:
            self._points = xyz

    def pose(self):
        with self._lock:
            return self._pose

    def points(self):
        with self._lock:
            return self._points


# ----------------------------------------------------------------------
# HTTP service
# ----------------------------------------------------------------------

def list_routes(folder: str) -> list[dict]:
    out = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(".json"):
                try:
                    r = Route.load(os.path.join(folder, name))
                    out.append({"name": r.name, "title_en": r.title_en, "title_de": r.title_de,
                                "home_scan": os.path.isfile(home_scan_path(os.path.join(folder, name))),
                                "length_m": round(r.length, 1), "created": r.created,
                                "kind": "tour" if r.stops else "route",
                                "stops": [{"name": st.get("name"), "title_en": st.get("title_en"),
                                           "title_de": st.get("title_de")} for st in r.stops]})
                except Exception:
                    pass
    return out


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            return

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/guide/routes":
                self._json(200, list_routes(service.routes_dir))
            elif path == "/api/guide/status":
                self._json(200, service.runner.snapshot())
            elif path == "/api/guide/pose":
                self._json(200, service.pose())
            else:
                self._json(404, {"detail": "Not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                self._json(400, {"detail": "Invalid JSON"})
                return
            if path == "/api/guide/cancel":
                service.runner.cancel()
                self._json(200, service.runner.snapshot())
            elif path == "/api/guide/start":
                ok, msg = service.start(body)
                self._json(200 if ok else 409, {"detail": msg, **service.runner.snapshot()})
            else:
                self._json(404, {"detail": "Not found"})

    return Handler


RUNS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs", "runs.jsonl")


def append_run(record: dict, path: str = RUNS_FILE) -> None:
    """One JSON line per guide / tour run (read by G1 Studio -> Evaluation)."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    if new:
        try:
            os.chmod(path, 0o666)
            os.chmod(os.path.dirname(path), 0o777)
        except OSError:
            pass


class GuideService:
    def __init__(self, runner: GuideRunner, routes_dir: str):
        self.runner = runner
        self.routes_dir = routes_dir
        self.thread: threading.Thread | None = None
        if getattr(runner, "run_logger", None) is None:
            runner.run_logger = append_run

    def pose(self) -> dict:
        """Live pose for G1 Studio. session = this FAST-LIO run (origin = HOME when
        guide mode was started); aligned = teaching frame of the running route."""
        r = self.runner
        raw_sensors = getattr(r, "_raw_sensors", None) or r.sensors
        out = {"session": None, "aligned": None, "route": None, "age_s": None,
               "state": r.status.state}
        try:
            p = raw_sensors.pose()
            if p is not None:
                out["session"] = [round(p[1], 3), round(p[2], 3), round(p[4], 4)]
                out["age_s"] = round(time.monotonic() - p[0], 2)
            running = self.thread is not None and self.thread.is_alive()
            if running and r.sensors is not raw_sensors:
                a = r.sensors.pose()
                if a is not None:
                    out["aligned"] = [round(a[1], 3), round(a[2], 3), round(a[4], 4)]
            if running:
                out["route"] = r.status.route
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def start(self, body: dict) -> tuple[bool, str]:
        if self.thread is not None and self.thread.is_alive():
            return False, "A guide is already running."
        name = str(body.get("route", ""))
        path = os.path.join(self.routes_dir, f"{name}.json")
        if not name or not os.path.isfile(path):
            return False, f"Unknown route '{name}'."
        route = load_route(path)
        try:
            self.runner.preflight()
        except SafetyError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Teleop server not reachable: {exc}"
        self.thread = threading.Thread(
            target=self.runner.run, name="guide",
            args=(route, str(body.get("lang", "en")), bool(body.get("return_home", True)),
                  float(body.get("wait_s", 20.0))), daemon=True)
        self.thread.start()
        return True, "started"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--routes", default=os.path.abspath(ROUTES_DIR))
    ap.add_argument("--teleop", default="http://127.0.0.1:8001")
    ap.add_argument("--voice", default="http://127.0.0.1:8766")
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument("--odom-topic", default="/Odometry")
    ap.add_argument("--cloud-topic", default="/cloud_registered")
    ap.add_argument("--obstacle-half-width", type=float, default=None,
                    help="m left/right of the path that must be free (default 0.40)")
    ap.add_argument("--obstacle-min-height", type=float, default=None,
                    help="ignore points lower than this above the floor (default 0.25)")
    ap.add_argument("--obstacle-min-points", type=int, default=None,
                    help="points needed to count as blocked (default 8)")
    args = ap.parse_args()

    pin = os.environ.get("G1_TELEOP_PIN", "")
    if not pin:
        sys.exit("Set G1_TELEOP_PIN (same PIN as the teleop server).")

    motion = TeleopMotion(args.teleop, pin)
    params = FollowParams()
    try:   # use the real limits of the running teleop server
        lim = motion.status().get("limits", {})
        params.max_forward_mps = float(lim.get("max_vx_forward", params.max_forward_mps))
        params.max_yaw_rate = float(lim.get("max_yaw", params.max_yaw_rate))
    except Exception as exc:
        print(f"[guide] WARNING: teleop server not reachable yet ({exc})")
    print(f"[guide] speed limits: {params.max_forward_mps} m/s, {params.max_yaw_rate} rad/s")
    for name in ("obstacle_half_width", "obstacle_min_height", "obstacle_min_points"):
        val = getattr(args, name)
        if val is None:
            env = os.environ.get("G1_GUIDE_" + name.upper())
            val = (int(env) if name.endswith("points") else float(env)) if env else None
        if val is not None:
            setattr(params, name, val)
    print(f"[guide] obstacle box: +-{params.obstacle_half_width} m, from {params.obstacle_min_height} m high, "
          f">= {params.obstacle_min_points} points")

    sensors = RosSensors(args.odom_topic, args.cloud_topic)
    runner = GuideRunner(motion, sensors, Voice(args.voice), params)
    service = GuideService(runner, args.routes)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(service))
    print(f"[guide] routes in {args.routes}: {[r['name'] for r in list_routes(args.routes)]}")
    print(f"[guide] listening on http://0.0.0.0:{args.port}/api/guide/...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.cancel()
        time.sleep(0.5)
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
