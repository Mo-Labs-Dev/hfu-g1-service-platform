import math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from home_align import align, apply, slice_2d
from test_guide_runner import World, runner
from test_route_core import l_route

LIDAR_H = 1.21


def room_points():
    """Lab-like room in the TEACHING frame (z = LiDAR-relative, walls 0.4-2 m high)."""
    pts = []
    for h in (-0.6, 0.0, 0.5):
        for x in np.arange(-3, 9, 0.04):
            pts += [[x, -3, h], [x, 7, h]]
        for y in np.arange(-3, 7, 0.04):
            pts += [[-3, y, h], [9, y, h]]
        for cx, cy in ((3.0, 2.5), (1.5, -2.0), (8.0, 5.5)):
            for a in np.arange(-0.4, 0.4, 0.04):
                pts += [[cx + a, cy - 0.4, h], [cx + a, cy + 0.4, h], [cx - 0.4, cy + a, h], [cx + 0.4, cy + a, h]]
    return np.array(pts)


def inv(T, xy):
    tx, ty, th = T
    c, s = math.cos(-th), math.sin(-th)
    d = np.asarray(xy) - [tx, ty]
    return np.stack([c * d[:, 0] - s * d[:, 1], s * d[:, 0] + c * d[:, 1]], axis=1)


class PlacedWorld(World):
    """G1 is placed slightly wrong on HOME. FAST-LIO starts there, so the odometry
    frame is G1's start pose; the route was taught in the (correct) teaching frame."""
    def __init__(self, place):
        super().__init__(x=place[0], y=place[1], yaw=place[2])
        self.place = place                       # odometry frame -> teaching frame
        self.room = room_points()
    def pose(self):
        (ox, oy), = inv(self.place, [[self.x, self.y]])
        return (self.t, float(ox), float(oy), self.z, self.yaw - self.place[2])
    def points(self):
        pts = self.room.copy()
        pts[:, :2] = inv(self.place, pts[:, :2])
        return pts


def test_icp_recovers_placement_error():
    home = slice_2d(room_points(), LIDAR_H)
    T_true = (0.15, -0.08, math.radians(6))
    cur = inv(T_true, home)
    T, fit, rmse = align(cur, home)
    assert abs(T[0] - 0.15) < 0.02 and abs(T[1] + 0.08) < 0.02
    assert abs(math.degrees(T[2]) - 6) < 0.3 and fit > 0.9


def test_guide_corrects_wrong_placement():
    place = (0.10, -0.08, math.radians(9))
    route = l_route()
    route.home_xy = slice_2d(room_points(), LIDAR_H)
    w = PlacedWorld(place); g = runner(w)
    assert g.run(route, "en", return_home=False) == "done"
    assert math.hypot(w.x - 6.0, w.y - 4.0) < 0.35          # real end of the taught route
    a = g.snapshot()["alignment"]
    assert a["used"] and abs(a["dyaw_deg"] - 9) < 0.5


def test_without_home_scan_the_error_stays():
    place = (0.10, -0.08, math.radians(9))
    w = PlacedWorld(place); g = runner(w)
    assert g.run(l_route(), "en", return_home=False) == "done"
    assert math.hypot(w.x - 6.0, w.y - 4.0) > 0.6           # rotated route: ends elsewhere
    assert g.snapshot()["alignment"]["used"] is False


def test_unrecognised_home_refuses_to_start():
    route = l_route()
    route.home_xy = slice_2d(room_points(), LIDAR_H) + [20.0, 0.0]   # different room
    w = PlacedWorld((0.0, 0.0, 0.0)); g = runner(w)
    assert g.run(route, "en") == "aborted"
    assert "HOME check failed" in g.status.message and "begin" not in w.events
