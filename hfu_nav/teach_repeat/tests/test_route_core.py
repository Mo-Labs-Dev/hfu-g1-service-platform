import math, sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from route_core import (Follower, FollowParams, OdometryWatch, Route, RouteRecorder,
                        SafetyError, obstacle_points_in_box, wrap, yaw_from_quaternion)

def l_route():
    """Teach by 'driving': 6 m straight, 90 deg left turn, 4 m straight."""
    rec = RouteRecorder("coffee_machine")
    for i in range(61):
        rec.add(i * 0.1, 0.0, 0.0, 0.0)
    for i in range(1, 41):
        rec.add(6.0, i * 0.1, 0.0, math.pi / 2)
    return rec.finish(title_en="coffee machine")

class SimG1:
    """Kinematic G1: integrates normalized commands at 10 Hz (server limits)."""
    def __init__(self, x=0.0, y=0.0, yaw=0.0, p=FollowParams()):
        self.x, self.y, self.yaw, self.p = x, y, yaw, p
    def apply(self, cmd, dt=0.1):
        v = cmd.x * self.p.max_forward_mps
        w = cmd.yaw * self.p.max_yaw_rate
        self.yaw = wrap(self.yaw + w * dt)
        self.x += v * math.cos(self.yaw) * dt
        self.y += v * math.sin(self.yaw) * dt

def run(route, robot, steps=3000, obstacle_at=None, align_end=False):
    f = Follower(route, align_end=align_end)
    f.check_start(robot.x, robot.y, robot.yaw)
    states, max_cross = [], 0.0
    for k in range(steps):
        obs = 20 if obstacle_at and obstacle_at[0] <= k < obstacle_at[1] else 0
        cmd = f.step(robot.x, robot.y, robot.yaw, obs)
        states.append(cmd.state)
        if cmd.state == "arrived":
            return f, robot, states, k
        robot.apply(cmd)
        d = np.min(np.hypot(route.xy[:, 0] - robot.x, route.xy[:, 1] - robot.y))
        max_cross = max(max_cross, d)
    raise AssertionError(f"did not arrive; last state {states[-1]}")

def test_recorder_spacing_and_length():
    r = l_route()
    assert 9.8 < r.length < 10.2
    assert r.start_yaw == 0.0 and abs(r.end_yaw - math.pi / 2) < 1e-9

def test_follows_l_route_to_goal(tmp_path):
    r = l_route()
    path = r.save(str(tmp_path)); r2 = Route.load(path)
    f, g1, states, k = run(r2, SimG1())
    assert math.hypot(g1.x - 6.0, g1.y - 4.0) < 0.35
    assert "turning" in states                     # turned at the corner
    assert k * 0.1 < 80                            # ~10 m at 0.25 m/s + turn

def test_stays_close_to_route():
    r = l_route(); g1 = SimG1()
    f = Follower(r)
    worst = 0.0
    for _ in range(3000):
        cmd = f.step(g1.x, g1.y, g1.yaw)
        if cmd.state == "arrived": break
        g1.apply(cmd)
        worst = max(worst, float(np.min(np.hypot(r.xy[:, 0] - g1.x, r.xy[:, 1] - g1.y))))
    assert worst < 0.35

def test_stops_for_obstacle_then_continues():
    r = l_route(); g1 = SimG1()
    f, g1, states, k = run(r, g1, obstacle_at=(50, 120))
    blocked = [s for s in states[50:120]]
    assert all(s == "blocked" for s in blocked)
    assert states[-1] == "arrived"

def test_return_route_and_align_home():
    r = l_route()
    g1 = SimG1(6.0, 4.0, math.pi / 2)
    g1.yaw = wrap(math.pi / 2 + math.pi)           # turned around at the goal
    back = r.reversed()
    f, g1, states, _ = run(back, g1, align_end=True)
    assert math.hypot(g1.x, g1.y) < 0.35
    assert abs(math.degrees(wrap(g1.yaw - back.end_yaw))) < 11

def test_refuses_when_not_at_home():
    r = l_route()
    with pytest.raises(SafetyError):
        Follower(r).check_start(2.0, 0.0, 0.0)
    with pytest.raises(SafetyError):
        Follower(r).check_start(0.0, 0.0, math.radians(60))

def test_aborts_when_lost():
    r = l_route(); f = Follower(r)
    with pytest.raises(SafetyError):
        f.step(0.0, 2.0, 0.0)

def test_odometry_watch_jump_and_height():
    w = OdometryWatch(FollowParams())
    w.update(0.0, 0, 0, 0); w.update(0.1, 0.02, 0, 0)
    with pytest.raises(SafetyError):
        w.update(0.2, 3.0, 0, 0)                   # FAST-LIO runaway
    w2 = OdometryWatch(FollowParams())
    w2.update(0.0, 0, 0, 0)
    with pytest.raises(SafetyError):
        w2.update(0.1, 0.01, 0, 0.8)               # height runaway

def test_obstacle_box():
    p = FollowParams()
    lidar = np.array([0.0, 0.0, 0.0])
    person = np.array([[0.8, y, z] for y in np.linspace(-0.2, 0.2, 5) for z in (-0.9, -0.6, -0.3)])
    beside = person + [0.0, 1.0, 0.0]
    floor = np.array([[0.8, 0.0, -1.2]] * 30)
    assert obstacle_points_in_box(person, lidar, 0.0, p) >= p.obstacle_min_points
    assert obstacle_points_in_box(beside, lidar, 0.0, p) == 0
    assert obstacle_points_in_box(floor, lidar, 0.0, p) == 0       # floor ignored
    # facing +90 deg: person now behind/side -> not counted
    assert obstacle_points_in_box(person, lidar, math.pi / 2, p) == 0

def test_yaw_from_quaternion_upright_and_inverted():
    q = (0, 0, math.sin(0.3 / 2), math.cos(0.3 / 2))
    assert abs(yaw_from_quaternion(*q) - 0.3) < 1e-9
    # roll pi (sensor upside down) then yaw 0.3: heading still 0.3
    from math import cos, sin
    cy, sy, cr, sr = cos(0.15), sin(0.15), cos(math.pi / 2), sin(math.pi / 2)
    qx, qy, qz, qw = sr * cy, sr * sy, cr * sy, cr * cy
    assert abs(yaw_from_quaternion(qx, qy, qz, qw) - 0.3) < 1e-6


def _wall(x0, x1, y, z=-0.6):
    return np.array([[x, y, z + dz] for x in np.arange(x0, x1, 0.02) for dz in (-0.3, 0.0, 0.3)])


def test_path_corridor_ignores_walls_beside_the_route():
    from route_core import obstacle_points_on_path
    p = FollowParams()
    path = np.array([[x, 0.0] for x in np.arange(0, 3, 0.05)])
    lidar = (0.0, 0.0, 0.0)
    assert obstacle_points_on_path(_wall(0.3, 1.5, 0.36), lidar, 0.0, path, p) == 0   # wall at 36 cm
    person = np.array([[1.0, y, -0.6] for y in np.arange(-0.2, 0.2, 0.02)])
    assert obstacle_points_on_path(person, lidar, 0.0, path, p) >= p.obstacle_min_points


def test_path_corridor_follows_a_curve():
    """Route turns right; a door frame straight ahead-left (old box: blocked) is ignored,
    a person standing on the curved path is still seen."""
    from route_core import obstacle_points_on_path
    p = FollowParams()
    path = np.array([[0.5 * math.sin(a), -0.5 + 0.5 * math.cos(a)] for a in np.linspace(0, math.pi / 2, 40)])
    lidar = (0.0, 0.0, 0.0)
    frame = np.array([[1.1, 0.27, -0.6 + dz] for dz in np.linspace(-0.4, 0.4, 20)])
    assert obstacle_points_in_box(frame, lidar, 0.0, p) >= 0                 # (old check)
    assert obstacle_points_on_path(frame, lidar, 0.0, path, p) == 0
    person = np.array([[0.5 + dx, -0.6 + dy, -0.6 + dz] for dx in (0, .05) for dy in (0, .05)
                       for dz in (-0.3, 0, 0.3)])
    assert obstacle_points_on_path(person, lidar, 0.0, path, p) >= p.obstacle_min_points


def test_path_ahead_is_dense_and_starts_at_robot():
    f = Follower(l_route())
    ahead = f.path_ahead(1.6)
    assert np.allclose(ahead[0], f.xy[0])
    assert np.max(np.linalg.norm(np.diff(ahead, axis=0), axis=1)) <= 0.051
