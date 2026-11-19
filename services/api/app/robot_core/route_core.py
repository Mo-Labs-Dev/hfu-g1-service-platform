"""
Teach & repeat core logic (no ROS, no network - unit tested).

Frames: everything is in FAST-LIO's odometry frame (camera_init) of a run
that was STARTED AT THE HOME SPOT. Teaching and guiding must both start
FAST-LIO with G1 standing on the marked home spot, facing the marked way.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, field

import numpy as np


# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------

def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    """Heading of the body x axis projected onto the ground plane.
    Works also when the sensor body is mounted upside down (roll = pi)."""
    fx = 1 - 2 * (y * y + z * z)
    fy = 2 * (x * y + w * z)
    return math.atan2(fy, fx)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# ----------------------------------------------------------------------
# Route
# ----------------------------------------------------------------------

@dataclass
class Route:
    name: str
    points: list[list[float]]           # [[x, y, z], ...] every ~spacing m
    start_yaw: float
    end_yaw: float
    created: str = ""
    spacing: float = 0.10
    title_en: str = ""
    title_de: str = ""
    arrival_en: str = ""
    arrival_de: str = ""
    # Lab tour: stops marked while teaching. Each stop:
    # {"index": point index, "name", "yaw", "title_en", "title_de", "text_en", "text_de"}
    stops: list[dict] = field(default_factory=list)

    @property
    def xy(self) -> np.ndarray:
        return np.asarray(self.points, dtype=float)[:, :2]

    @property
    def length(self) -> float:
        xy = self.xy
        return float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum()) if len(xy) > 1 else 0.0

    @property
    def is_tour(self) -> bool:
        return bool(self.stops)

    @property
    def is_loop(self) -> bool:
        """Route ends where it started (a tour that comes back home by itself)."""
        a, b = self.points[0], self.points[-1]
        return len(self.points) > 20 and math.hypot(a[0] - b[0], a[1] - b[1]) < 1.0

    def segment(self, i0: int, i1: int, end_yaw: float | None = None, name: str = "") -> "Route":
        """Part of the route from point i0 to i1 (inclusive)."""
        pts = self.points[i0:i1 + 1]
        if len(pts) < 2:
            pts = self.points[max(0, i1 - 1):i1 + 1]
        return Route(name=name or f"{self.name}_{i0}_{i1}", points=pts,
                     start_yaw=self.start_yaw,
                     end_yaw=self.end_yaw if end_yaw is None else end_yaw,
                     created=self.created, spacing=self.spacing)

    def reversed(self) -> "Route":
        return Route(name=self.name + "_return", points=self.points[::-1],
                     start_yaw=wrap(self.end_yaw + math.pi),
                     end_yaw=wrap(self.start_yaw + math.pi),
                     created=self.created, spacing=self.spacing,
                     title_en="home", title_de="nach Hause")

    def save(self, folder: str) -> str:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{self.name}.json")
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=1)
        return path

    @staticmethod
    def load(path: str) -> "Route":
        with open(path) as f:
            return Route(**json.load(f))


class RouteRecorder:
    """Collects odometry while you drive with the joystick."""

    def __init__(self, name: str, spacing: float = 0.10):
        self.name = name
        self.spacing = spacing
        self.points: list[list[float]] = []
        self.yaws: list[float] = []
        self.latest: tuple[float, float, float, float] | None = None
        self.stops: list[dict] = []

    def mark_stop(self, name: str = "") -> dict:
        """Tour stop at the current position. Turn G1 to face the exhibit first:
        the current heading is stored and G1 turns that way when explaining."""
        if self.latest is None:
            raise ValueError("No odometry yet.")
        x, y, z, yaw = self.latest
        if not self.points or math.hypot(x - self.points[-1][0], y - self.points[-1][1]) > 0.01:
            self.points.append([x, y, z])
            self.yaws.append(yaw)
        idx = len(self.points) - 1
        if self.stops and idx - self.stops[-1]["index"] < 5:
            raise ValueError("Too close to the previous stop (walk at least 0.5 m).")
        name = (name or f"stop_{len(self.stops) + 1}").strip().replace(" ", "_")
        title = name.replace("_", " ")
        stop = {"index": idx, "name": name, "yaw": round(yaw, 4),
                "title_en": title, "title_de": title, "text_en": "", "text_de": ""}
        self.stops.append(stop)
        return stop

    def add(self, x: float, y: float, z: float, yaw: float) -> bool:
        self.latest = (x, y, z, yaw)
        if not self.points:
            self.points.append([x, y, z])
            self.yaws.append(yaw)
            return True
        last = self.points[-1]
        if math.hypot(x - last[0], y - last[1]) >= self.spacing * 0.999:
            self.points.append([x, y, z])
            self.yaws.append(yaw)
            return True
        return False

    def finish(self, **titles) -> Route:
        # Always end exactly where the robot stopped while teaching.
        if self.latest is not None and self.points:
            x, y, z, yaw = self.latest
            if math.hypot(x - self.points[-1][0], y - self.points[-1][1]) > 0.01:
                self.points.append([x, y, z])
                self.yaws.append(yaw)
            else:
                self.yaws[-1] = yaw
        if len(self.points) < 5:
            raise ValueError("Route too short - drive at least 0.5 m.")
        return Route(name=self.name, points=[[round(v, 4) for v in p] for p in self.points],
                     start_yaw=self.yaws[0], end_yaw=self.yaws[-1],
                     created=time.strftime("%Y-%m-%d %H:%M:%S"),
                     spacing=self.spacing, stops=[dict(st) for st in self.stops], **titles)


# ----------------------------------------------------------------------
# Follower (pure pursuit + safety)
# ----------------------------------------------------------------------

@dataclass
class FollowParams:
    lookahead: float = 0.6            # m
    cruise: float = 1.0               # normalized forward (x max_forward of server)
    min_forward: float = 0.65         # normalized; G1 does not walk below ~0.15 m/s
    max_yaw_rate: float = 0.30        # rad/s at normalized 1.0 (server --max-yaw)
    max_forward_mps: float = 0.25     # m/s at normalized 1.0 (server --max-forward)
    turn_in_place_deg: float = 40.0   # bigger heading error -> turn in place first
    turn_done_deg: float = 15.0
    turn_rate: float = 0.21           # rad/s while turning in place / aligning (tested value)
    follow_max_yaw_rate: float = 0.30 # rad/s cap while walking the route (tested value)
    goal_tolerance: float = 0.30      # m
    align_tolerance_deg: float = 10.0
    slow_down_dist: float = 1.0       # m before goal
    max_cross_track: float = 0.8      # m -> abort (lost the route)
    start_max_dist: float = 0.6       # m from route start to begin
    start_max_yaw_deg: float = 25.0
    odom_pause_age: float = 0.5       # s: no odometry -> stand still
    odom_abort_age: float = 2.0       # s: no odometry -> abort
    odom_max_jump: float = 0.4        # m between consecutive odometry msgs
    max_z_drift: float = 0.5          # m from start height (FAST-LIO runaway)
    # Obstacle box in front of the robot (heading frame, origin at LiDAR).
    obstacle_ahead_min: float = 0.2
    obstacle_ahead_max: float = 1.2
    # Corridor around the TAUGHT PATH (+-m). G1's body reaches ~0.23 m left/right of the
    # taught line, so walls/door frames that G1 passed while teaching are always further
    # away than 0.20 m (minus odometry drift). Anything nearer to the line is new.
    obstacle_half_width: float = 0.20
    obstacle_core_half_width: float = 0.15  # plus a narrow straight box right in front
    lidar_height: float = 1.21        # m above floor (Session 03: 1.21 m)
    obstacle_min_height: float = 0.25 # m above floor
    obstacle_max_height: float = 1.60
    obstacle_min_points: int = 8
    turn_clear_radius: float = 0.6    # m: obstacle check while turning in place


@dataclass
class Command:
    x: float = 0.0          # normalized forward
    yaw: float = 0.0        # normalized turn (left +)
    state: str = "idle"     # following / turning / aligning / blocked / arrived / aborted / paused
    message: str = ""
    progress: float = 0.0   # 0..1


class SafetyError(Exception):
    pass


class OdometryWatch:
    """Detects stale odometry, jumps and height runaway (FAST-LIO divergence)."""

    def __init__(self, p: FollowParams):
        self.p = p
        self.last: tuple[float, float, float, float] | None = None   # t, x, y, z
        self.z0: float | None = None

    def update(self, t: float, x: float, y: float, z: float) -> None:
        if self.last is not None:
            dt = max(1e-3, t - self.last[0])
            jump = math.hypot(x - self.last[1], y - self.last[2])
            if jump > self.p.odom_max_jump and jump / dt > 2.0:
                raise SafetyError(f"Odometry jumped {jump:.2f} m - stopping (FAST-LIO problem?)")
        if self.z0 is None:
            self.z0 = z
        if abs(z - self.z0) > self.p.max_z_drift:
            raise SafetyError(f"Odometry height drifted {z - self.z0:+.2f} m - stopping (FAST-LIO problem?)")
        self.last = (t, x, y, z)

    def age(self, now: float) -> float:
        return float("inf") if self.last is None else now - self.last[0]


def obstacle_points_in_box(points: np.ndarray, pose_xyz, yaw: float, p: FollowParams,
                           turning: bool = False) -> int:
    """Count map-frame points inside the stop box in front of the robot."""
    if points is None or len(points) == 0:
        return 0
    d = np.asarray(points, dtype=float)[:, :3] - np.asarray(pose_xyz, dtype=float)
    c, s = math.cos(yaw), math.sin(yaw)
    fwd = d[:, 0] * c + d[:, 1] * s
    side = -d[:, 0] * s + d[:, 1] * c
    height = d[:, 2] + p.lidar_height          # height above floor
    band = (height > p.obstacle_min_height) & (height < p.obstacle_max_height)
    if turning:
        r = np.hypot(fwd, side)
        box = (r > 0.25) & (r < p.turn_clear_radius)
    else:
        box = ((fwd > p.obstacle_ahead_min) & (fwd < p.obstacle_ahead_max)
               & (np.abs(side) < p.obstacle_half_width))
    return int(np.count_nonzero(band & box))


def obstacle_points_on_path(points: np.ndarray, pose_xyz, yaw: float, path_xy: np.ndarray,
                            p: FollowParams) -> int:
    return int(np.count_nonzero(obstacle_mask_on_path(points, pose_xyz, yaw, path_xy, p)[0]))


def obstacle_mask_on_path(points, pose_xyz, yaw: float, path_xy, p: FollowParams):
    """Count points that are really in G1's way: in the height band, 0.2-1.2 m away,
    in front, AND either close to the taught path ahead (corridor that bends with the
    route, so walls / door frames beside a curve are ignored) or straight in front
    of G1 (narrow core box)."""
    if points is None or len(points) == 0:
        return np.zeros(0, dtype=bool), {}
    pts = np.asarray(points, dtype=float)[:, :3]
    d = pts - np.asarray(pose_xyz, dtype=float)
    c, s = math.cos(yaw), math.sin(yaw)
    fwd = d[:, 0] * c + d[:, 1] * s
    side = -d[:, 0] * s + d[:, 1] * c
    height = d[:, 2] + p.lidar_height
    dist = np.hypot(d[:, 0], d[:, 1])
    cand = ((height > p.obstacle_min_height) & (height < p.obstacle_max_height)
            & (dist > p.obstacle_ahead_min) & (dist < p.obstacle_ahead_max) & (fwd > 0.1))
    info = {"fwd": fwd, "side": side, "height": height, "to_path": np.full(len(pts), np.inf)}
    if not cand.any():
        return np.zeros(len(pts), dtype=bool), info
    core = cand & (np.abs(side) < p.obstacle_core_half_width)
    on_path = np.zeros_like(cand)
    if path_xy is not None and len(path_xy):
        idx = np.nonzero(cand)[0]
        q = pts[idx, :2]
        path = np.asarray(path_xy, dtype=float)[:, :2]
        nearest = np.min(np.hypot(q[:, None, 0] - path[None, :, 0],
                                  q[:, None, 1] - path[None, :, 1]), axis=1)
        on_path[idx] = nearest < p.obstacle_half_width
        info["to_path"][idx] = nearest
    return core | on_path, info


class Follower:
    def path_ahead(self, length: float = 1.6) -> np.ndarray:
        """Taught route points from G1's current position up to `length` m ahead
        (densified to 5 cm so the corridor has no gaps)."""
        end = int(np.searchsorted(self.cum, self.cum[self.idx] + length)) + 1
        seg = self.xy[self.idx:min(len(self.xy), end + 1)]
        if len(seg) < 2:
            return seg
        out = [seg[0]]
        for a, b in zip(seg[:-1], seg[1:]):
            n = max(1, int(math.ceil(math.hypot(*(b - a)) / 0.05)))
            out.extend(a + (b - a) * k / n for k in range(1, n + 1))
        return np.asarray(out)

    @property
    def turn_norm(self) -> float:
        """Normalized turn command giving p.turn_rate rad/s, whatever the server's
        --max-yaw is (the joystick may allow faster turning than the guide)."""
        return min(1.0, self.p.turn_rate / self.p.max_yaw_rate)

    def __init__(self, route: Route, p: FollowParams | None = None, align_end: bool = False):
        self.route = route
        self.p = p or FollowParams()
        self.xy = route.xy
        seg = np.linalg.norm(np.diff(self.xy, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.total = float(self.cum[-1])
        self.idx = 0
        self.turning = False
        self.align_end = align_end
        self.done = False

    def check_start(self, x: float, y: float, yaw: float) -> None:
        d = math.hypot(x - self.xy[0, 0], y - self.xy[0, 1])
        dyaw = abs(math.degrees(wrap(yaw - self.route.start_yaw)))
        if d > self.p.start_max_dist or dyaw > self.p.start_max_yaw_deg:
            raise SafetyError(
                f"G1 is not at the start of the route ({d:.2f} m, {dyaw:.0f} deg away). "
                "Place G1 on the home spot and restart FAST-LIO there.")

    def step(self, x: float, y: float, yaw: float, obstacle_count: int = 0) -> Command:
        p = self.p
        if self.done:
            return Command(state="arrived", progress=1.0)

        # Nearest route point, searching forward only (monotonic progress).
        window = self.xy[self.idx:min(len(self.xy), self.idx + 40)]
        dists = np.hypot(window[:, 0] - x, window[:, 1] - y)
        self.idx += int(np.argmin(dists))
        cross = float(dists.min())
        if cross > p.max_cross_track:
            raise SafetyError(f"G1 is {cross:.2f} m away from the taught route - stopping.")
        remaining = self.total - self.cum[self.idx]
        progress = float(self.cum[self.idx] / self.total) if self.total else 1.0

        end = self.xy[-1]
        to_end = math.hypot(end[0] - x, end[1] - y)
        # Arrived only when really at the end point (not just "far along").
        if to_end < p.goal_tolerance and remaining < p.lookahead:
            if self.align_end:
                err = wrap(self.route.end_yaw - yaw)
                if abs(math.degrees(err)) > p.align_tolerance_deg:
                    return Command(yaw=math.copysign(self.turn_norm, err), state="aligning",
                                   progress=1.0, message="Turning to the final direction")
            self.done = True
            return Command(state="arrived", progress=1.0)

        # Lookahead point.
        target_i = int(np.searchsorted(self.cum, self.cum[self.idx] + p.lookahead))
        target = self.xy[min(target_i, len(self.xy) - 1)]
        alpha = wrap(math.atan2(target[1] - y, target[0] - x) - yaw)
        deg = abs(math.degrees(alpha))

        if self.turning and deg < p.turn_done_deg:
            self.turning = False
        elif not self.turning and deg > p.turn_in_place_deg:
            self.turning = True

        if obstacle_count >= p.obstacle_min_points:
            return Command(state="blocked", progress=progress,
                           message="Something is in front of me - waiting")

        if self.turning:
            return Command(yaw=math.copysign(self.turn_norm, alpha), state="turning",
                           progress=progress)

        forward = p.cruise
        if remaining < p.slow_down_dist:
            forward = max(p.min_forward, p.cruise * max(remaining, to_end) / p.slow_down_dist)
        v = forward * p.max_forward_mps
        omega = v * 2 * math.sin(alpha) / p.lookahead           # pure pursuit
        cap = min(p.max_yaw_rate, p.follow_max_yaw_rate)
        omega = max(-cap, min(cap, omega))
        yaw_norm = max(-1.0, min(1.0, omega / p.max_yaw_rate))
        return Command(x=forward, yaw=yaw_norm, state="following", progress=progress)
