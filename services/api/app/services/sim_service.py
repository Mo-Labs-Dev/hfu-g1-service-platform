"""
G1 Studio simulator + path planner (on the real Session 03 map).

Simulation runs the REAL guide code (app/robot_core = copy of the robot's
guide_runner.py / route_core.py) against a simulated G1:
  - kinematics with the teleop server's speed / acceleration limits
  - simulated LiDAR: map walls + virtual people, with the LiDAR blind zone
  - simulated clock (a 5 min tour is simulated in about a second)
The result is a timeline that the browser plays back.

Planner: A* on the map (0.1 m cells) that keeps >= 0.30 m from walls
(G1 is ~0.46 m wide) and prefers the middle of corridors; result is smoothed.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys

import numpy as np

_CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "robot_core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from guide_runner import GuideRunner  # noqa: E402
from route_core import FollowParams, Route, wrap  # noqa: E402

from app.services.lab_map_service import lab_map  # noqa: E402

# teleop server limits (g1_start_all.sh: --max-forward 0.25, MAX_YAW 0.8)
MAX_FORWARD = float(os.getenv("G1_SIM_MAX_FORWARD", "0.25"))
MAX_YAW = float(os.getenv("G1_SIM_MAX_YAW", "0.8"))
ACCEL_LIN, DECEL_LIN, ACCEL_YAW, DECEL_YAW = 0.5, 1.0, 1.0, 2.0
LIDAR_BLIND = 1.0          # m (FAST-LIO blind)
SENSE_RANGE = 2.0          # m: points we generate around G1
ROBOT_HALF_WIDTH = 0.23
PLAN_CLEARANCE = 0.30      # m from walls for planned paths
PLAN_RES = 0.10


# ======================================================================== world model
class _Clearance:
    """Distance to the nearest wall for every map pixel (metres)."""

    def __init__(self):
        import cv2
        lab_map._load()
        g = lab_map._grid
        self.res = lab_map._meta["resolution"]
        self.ox, self.oy = lab_map._meta["origin"][:2]
        self.h, self.w = g.shape
        self.free = g >= 250                                     # floor seen while mapping
        wall_free = (g > 50).astype(np.uint8)                   # unknown counts as "not a wall"
        self.dist_wall = cv2.distanceTransform(wall_free, cv2.DIST_L2, 5) * self.res
        # explored area: within 0.4 m of floor that was seen (fills the speckle in the map)
        not_free = (~self.free).astype(np.uint8)
        self.explored = cv2.distanceTransform(not_free, cv2.DIST_L2, 5) * self.res <= 0.4
        self.walls = lab_map.walls()

    def rc(self, x, y):
        c = int(math.floor((x - self.ox) / self.res))
        r = int(math.floor(self.h - (y - self.oy) / self.res))
        return r, c

    def clearance(self, x, y) -> float:
        r, c = self.rc(x, y)
        if not (0 <= r < self.h and 0 <= c < self.w):
            return 0.0
        return float(self.dist_wall[r, c])


_clear: _Clearance | None = None


def clearance_model() -> _Clearance:
    global _clear
    if _clear is None:
        _clear = _Clearance()
    return _clear


class SimG1:
    """Simulated robot + sensors + voice + teleop server for GuideRunner."""

    def __init__(self, x, y, yaw, people, p: FollowParams):
        self.t = 0.0
        self.x, self.y, self.z, self.yaw = x, y, 0.0, yaw
        self.v = self.w = 0.0
        self.cmd_v = self.cmd_w = 0.0
        self.people = people or []
        self.p = p
        self.frames: list = []
        self.events: list = []
        self._next_frame = 0.0
        self.runner = None
        cm = clearance_model()
        self._walls = cm.walls
        self.limit_s = 3600.0

    # ---------------- clock / kinematics
    def clock(self):
        return self.t

    def sleep(self, dt):
        steps = max(1, int(round(dt / 0.05)))
        h = dt / steps
        for _ in range(steps):
            self.v = _ramp(self.v, self.cmd_v, ACCEL_LIN, DECEL_LIN, h)
            self.w = _ramp(self.w, self.cmd_w, ACCEL_YAW, DECEL_YAW, h)
            self.yaw = wrap(self.yaw + self.w * h)
            self.x += self.v * math.cos(self.yaw) * h
            self.y += self.v * math.sin(self.yaw) * h
            self.t += h
        if self.t >= self._next_frame:
            self._next_frame = self.t + 0.25
            st = self.runner.status if self.runner else None
            self.frames.append([round(self.t, 2), round(self.x, 3), round(self.y, 3), round(self.yaw, 3),
                                st.state if st else "", st.stop_index if st else 0,
                                round(st.progress, 3) if st else 0.0])
        if self.t > self.limit_s and self.runner:
            self.runner.cancel()

    # ---------------- teleop server
    def status(self):
        return {"fsm_id": 500, "estop": False, "teleop_active": False, "stop_count": 0}

    def begin(self):
        self.events.append([round(self.t, 1), "motion", "guide takes control"])

    def end(self):
        self.cmd_v = self.cmd_w = 0.0

    def send(self, x, yaw):
        self.cmd_v = max(-1.0, min(1.0, x)) * MAX_FORWARD
        self.cmd_w = max(-1.0, min(1.0, yaw)) * MAX_YAW

    def stopped_by_operator(self):
        return False

    # ---------------- sensors
    def pose(self):
        return (self.t, self.x, self.y, self.z, self.yaw)

    def points(self):
        pts = []
        near = self._walls[np.hypot(self._walls[:, 0] - self.x, self._walls[:, 1] - self.y) < SENSE_RANGE]
        for h in (0.4, 0.9, 1.4):
            if len(near):
                pts.append(np.column_stack([near, np.full(len(near), h - self.p.lidar_height)]))
        for person in self.people:
            if not (person.get("t_from", 0) <= self.t < person.get("t_to", 1e9)):
                continue
            px, py = person["x"], person["y"]
            if math.hypot(px - self.x, py - self.y) > SENSE_RANGE + 0.3:
                continue
            ang = np.linspace(0, 2 * math.pi, 24, endpoint=False)
            ring = np.column_stack([px + 0.22 * np.cos(ang), py + 0.22 * np.sin(ang)])
            for h in (0.3, 0.6, 0.9, 1.2, 1.5):
                pts.append(np.column_stack([ring, np.full(len(ring), h - self.p.lidar_height)]))
        if not pts:
            return np.zeros((0, 3))
        allp = np.vstack(pts)
        d3 = np.sqrt((allp[:, 0] - self.x) ** 2 + (allp[:, 1] - self.y) ** 2 + allp[:, 2] ** 2)
        return allp[d3 >= LIDAR_BLIND]                         # FAST-LIO blind zone

    # ---------------- voice
    def say(self, text, lang):
        self.events.append([round(self.t, 1), "say", text])
        return None


def _ramp(cur, target, acc, dec, h):
    if abs(target) < abs(cur) or cur * target < 0:
        step = dec * h
    else:
        step = acc * h
    if target > cur:
        return min(target, cur + step)
    return max(target, cur - step)


# ======================================================================== routes in map frame
def route_in_map(name: str) -> tuple[Route, str]:
    path = os.path.join(lab_map.routes_dir, f"{name}.json")
    if not os.path.isfile(path):
        raise KeyError(name)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    al = lab_map.alignment()
    a = al.get("routes", {}).get(name)
    if a and a.get("ok"):
        T, src = (a["tx"], a["ty"], a["theta"]), "scan"
    elif al.get("home"):
        h = al["home"]
        T, src = (h["x"], h["y"], h["yaw"]), "home"
    else:
        raise ValueError("Place HOME on the Lab Map first.")
    tx, ty, th = T
    c, s = math.cos(th), math.sin(th)
    pts = [[tx + c * p[0] - s * p[1], ty + s * p[0] + c * p[1], p[2] if len(p) > 2 else 0.0]
           for p in d["points"]]
    stops = []
    for st in d.get("stops", []):
        st = dict(st)
        if st.get("yaw") is not None:
            st["yaw"] = wrap(st["yaw"] + th)
        stops.append(st)
    r = Route(name=name, points=pts, start_yaw=wrap(d.get("start_yaw", 0.0) + th),
              end_yaw=wrap(d.get("end_yaw", 0.0) + th), created=d.get("created", ""),
              spacing=d.get("spacing", 0.1), title_en=d.get("title_en", ""), title_de=d.get("title_de", ""),
              arrival_en=d.get("arrival_en", ""), arrival_de=d.get("arrival_de", ""), stops=stops)
    return r, src


def route_from_path(path_xy: list, name="planned_path") -> Route:
    pts = densify(np.asarray(path_xy, float), 0.1)
    yaw0 = math.atan2(pts[1, 1] - pts[0, 1], pts[1, 0] - pts[0, 0]) if len(pts) > 1 else 0.0
    yaw1 = math.atan2(pts[-1, 1] - pts[-2, 1], pts[-1, 0] - pts[-2, 0]) if len(pts) > 1 else 0.0
    return Route(name=name, points=[[float(x), float(y), 0.0] for x, y in pts], start_yaw=yaw0,
                 end_yaw=yaw1, title_en="planned destination", title_de="geplantes Ziel")


def densify(pts: np.ndarray, step: float) -> np.ndarray:
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / step)))
        out.extend(a + (b - a) * k / n for k in range(1, n + 1))
    return np.asarray(out)


def narrow_spots(route: Route, limit: float = 0.25) -> list[dict]:
    """Places where the route passes closer than `limit` to a wall of the map."""
    cm = clearance_model()
    spots, last = [], None
    for x, y, *_ in route.points:
        c = cm.clearance(x, y)
        if c < limit and (last is None or math.hypot(x - last[0], y - last[1]) > 1.0):
            spots.append({"x": round(x, 2), "y": round(y, 2), "clearance_m": round(c, 2)})
            last = (x, y)
    return spots


# ======================================================================== simulate
def simulate(route: Route, lang="en", people=None, return_home=True, speed_check=True) -> dict:
    p = FollowParams(max_forward_mps=MAX_FORWARD, max_yaw_rate=MAX_YAW)
    sim = SimG1(route.points[0][0], route.points[0][1], route.start_yaw, people, p)
    runner = GuideRunner(motion=sim, sensors=sim, voice=sim, params=p, clock=sim.clock, sleep=sim.sleep)
    sim.runner = runner
    route.home_xy = None                                  # no HOME scan check in simulation
    result = runner.run(route, lang, return_home=return_home, wait_s=5.0)
    hist = runner.status.history
    blocked_s, since = 0.0, None
    for t, state, _ in hist:
        if state == "blocked" and since is None:
            since = t
        elif state != "blocked" and since is not None:
            blocked_s += t - since
            since = None
    states = [[round(t, 1), s, m] for t, s, m in hist]
    return {
        "result": result, "message": runner.status.message,
        "duration_s": round(sim.t, 1), "blocked_s": round(blocked_s, 1),
        "frames": sim.frames, "events": sim.events, "states": states,
        "stops": [{"name": s.get("name"), "title_en": s.get("title_en")} for s in route.stops],
        "narrow_spots": narrow_spots(route),
        "end_error_m": round(math.hypot(sim.x - (route.points[0][0] if return_home or route.stops
                                                  else route.points[-1][0]),
                                        sim.y - (route.points[0][1] if return_home or route.stops
                                                 else route.points[-1][1])), 2),
    }


# ======================================================================== A* planner
class Planner:
    def __init__(self):
        cm = clearance_model()
        f = int(round(PLAN_RES / cm.res))                    # 2 map pixels per plan cell
        h, w = cm.h // f, cm.w // f
        explored = cm.explored[: h * f, : w * f].reshape(h, f, w, f).all(axis=(1, 3))
        seen = cm.free[: h * f, : w * f].reshape(h, f, w, f).any(axis=(1, 3))
        clr = cm.dist_wall[: h * f, : w * f].reshape(h, f, w, f).min(axis=(1, 3))
        self.f, self.h, self.w = f, h, w
        self.ok = explored & (clr >= PLAN_CLEARANCE)
        self.seen = seen
        self.clr = clr
        self.ox, self.oy, self.mres, self.mh = cm.ox, cm.oy, cm.res, cm.h

    def cell(self, x, y):
        c = int(math.floor((x - self.ox) / PLAN_RES))
        r = int(math.floor((self.mh * self.mres - (y - self.oy)) / PLAN_RES))
        return r, c

    def xy(self, r, c):
        return (self.ox + (c + 0.5) * PLAN_RES, self.oy + self.mh * self.mres - (r + 0.5) * PLAN_RES)

    def snap(self, r, c, radius=12):
        if 0 <= r < self.h and 0 <= c < self.w and self.ok[r, c]:
            return r, c
        best = None
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < self.h and 0 <= cc < self.w and self.ok[rr, cc]:
                    d = dr * dr + dc * dc
                    if best is None or d < best[0]:
                        best = (d, rr, cc)
        if best is None:
            raise ValueError("Point is not in a free area of the map (too close to walls or unknown).")
        return best[1], best[2]

    def plan(self, start, goal) -> dict:
        s = self.snap(*self.cell(*start))
        g = self.snap(*self.cell(*goal))
        moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                 (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
        INF = float("inf")
        cost = np.full((self.h, self.w), INF)
        parent = -np.ones((self.h, self.w), dtype=np.int64)
        cost[s] = 0.0
        heap = [(0.0, s)]
        gr, gc = g
        while heap:
            f, (r, c) = heapq.heappop(heap)
            if (r, c) == g:
                break
            base = cost[r, c]
            if f - math.hypot(r - gr, c - gc) > base + 1e-9:
                continue
            for dr, dc, step in moves:
                rr, cc = r + dr, c + dc
                if not (0 <= rr < self.h and 0 <= cc < self.w) or not self.ok[rr, cc]:
                    continue
                penalty = 1.0 + 2.0 * max(0.0, 0.8 - float(self.clr[rr, cc]))   # keep to the middle
                if not self.seen[rr, cc]:
                    penalty *= 1.3                                          # prefer floor seen in the map
                nc = base + step * penalty
                if nc < cost[rr, cc]:
                    cost[rr, cc] = nc
                    parent[rr, cc] = r * self.w + c
                    heapq.heappush(heap, (nc + math.hypot(rr - gr, cc - gc), (rr, cc)))
        if not math.isfinite(cost[g]):
            raise ValueError("No safe path found between these points.")
        cells = [g]
        while cells[-1] != s:
            k = int(parent[cells[-1]])
            cells.append((k // self.w, k % self.w))
        cells.reverse()
        pts = [self.xy(r, c) for r, c in cells]
        smooth = self._shortcut(pts)
        arr = np.asarray(smooth)
        length = float(np.sum(np.hypot(*np.diff(arr, axis=0).T))) if len(arr) > 1 else 0.0
        dense = densify(arr, 0.1)
        cm = clearance_model()
        min_clear = min(cm.clearance(x, y) for x, y in dense)
        return {"path": [[round(x, 3), round(y, 3)] for x, y in smooth], "length_m": round(length, 2),
                "min_clearance_m": round(min_clear, 2), "start": list(self.xy(*s)), "goal": list(self.xy(*g))}

    def _free_line(self, a, b) -> bool:
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (PLAN_RES / 2)))
        for k in range(n + 1):
            x = a[0] + (b[0] - a[0]) * k / n
            y = a[1] + (b[1] - a[1]) * k / n
            r, c = self.cell(x, y)
            if not (0 <= r < self.h and 0 <= c < self.w) or not self.ok[r, c]:
                return False
        return True

    def _shortcut(self, pts):
        out, i = [pts[0]], 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not self._free_line(pts[i], pts[j]):
                j -= 1
            out.append(pts[j])
            i = j
        return out


_planner: Planner | None = None


def planner() -> Planner:
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner
