"""
Lab map (digital twin) for G1 Studio.

Frames
  map      Session 03 2D map (nav2d_session03, leveled, metres)
  teach    frame of a taught route = FAST-LIO frame of its recording run (origin ~ HOME)
  session  FAST-LIO frame of the running guide mode (origin = HOME at start)

Studio stores, per route, the transform teach -> map. It is found by matching the
route's HOME scan (routes/NAME.home.npz) against the walls of the map (2D ICP),
starting from the HOME pose the operator placed on the map. The session frame is
mapped with the HOME pose itself (FAST-LIO starts on HOME).
"""
from __future__ import annotations

import io
import json
import math
import os
import threading

import numpy as np

from app.services import home_align

_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
MAP_DIR = os.path.expanduser(os.getenv("G1_MAP_DIR", os.path.join(_DATA, "maps", "nav2d_session03")))
ROUTES_DIR = os.path.expanduser(os.getenv(
    "G1_ROUTES_DIR", "~/Documents/Projekte/g1pilot-main/hfu_nav/routes"))
STORE = os.path.expanduser(os.getenv(
    "G1_MAP_ALIGNMENT_FILE", os.path.join(_DATA, "map_alignment.json")))


def compose(a, b):
    """a after b: (a ∘ b)(p) = a(b(p)). Transforms are (tx, ty, theta)."""
    ax, ay, at = a
    bx, by, bt = b
    c, s = math.cos(at), math.sin(at)
    return (ax + c * bx - s * by, ay + s * bx + c * by, math.atan2(math.sin(at + bt), math.cos(at + bt)))


def apply_pose(T, pose):
    x, y, yaw = pose
    (mx, my), = home_align.apply(T, np.array([[x, y]]))
    return (float(mx), float(my), float(math.atan2(math.sin(yaw + T[2]), math.cos(yaw + T[2]))))


class LabMap:
    def __init__(self, map_dir: str = MAP_DIR, routes_dir: str = ROUTES_DIR, store: str = STORE):
        self.map_dir, self.routes_dir, self.store = map_dir, routes_dir, store
        self._lock = threading.Lock()
        self._grid = None
        self._png = None
        self._walls = None

    # ------------------------------------------------------------ map
    def _load(self):
        if self._grid is not None:
            return
        meta = {"resolution": 0.05, "origin": [0.0, 0.0, 0.0], "image": "map.pgm"}
        with open(os.path.join(self.map_dir, "map.yaml")) as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if k == "resolution":
                        meta["resolution"] = float(v)
                    elif k == "origin":
                        meta["origin"] = [float(x) for x in v.strip("[]").split(",")]
                    elif k == "image":
                        meta["image"] = v
        grid = read_pgm(os.path.join(self.map_dir, meta["image"]))
        self._grid, self._meta = grid, meta

    def info(self) -> dict:
        self._load()
        h, w = self._grid.shape
        res = self._meta["resolution"]
        ox, oy = self._meta["origin"][:2]
        return {"width_px": w, "height_px": h, "resolution": res, "origin": [ox, oy],
                "width_m": w * res, "height_m": h * res,
                # pixel (col,row) of map point (x,y): col=(x-ox)/res, row=h-1-(y-oy)/res
                "frame": "map (Session 03, leveled)"}

    def png(self) -> bytes:
        self._load()
        if self._png is None:
            import cv2
            g = self._grid
            img = np.full(g.shape + (3,), 245, np.uint8)          # unknown: light grey
            img[g >= 250] = (255, 255, 255)                          # free: white
            img[g <= 50] = (60, 66, 72)                               # occupied: dark
            ok, buf = cv2.imencode(".png", img)
            self._png = buf.tobytes()
        return self._png

    def walls(self) -> np.ndarray:
        """Occupied cells as map-frame points (for ICP)."""
        self._load()
        if self._walls is None:
            g = self._grid
            h, _ = g.shape
            rows, cols = np.nonzero(g <= 50)
            res = self._meta["resolution"]
            ox, oy = self._meta["origin"][:2]
            xs = ox + (cols + 0.5) * res
            ys = oy + (h - 1 - rows + 0.5) * res
            self._walls = np.stack([xs, ys], axis=1)
        return self._walls

    # ------------------------------------------------------------ alignment store
    def alignment(self) -> dict:
        try:
            with open(self.store) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"home": None, "routes": {}}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.store)), exist_ok=True)
        tmp = self.store + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.store)

    def set_home(self, x: float, y: float, yaw: float) -> dict:
        with self._lock:
            data = self.alignment()
            data["home"] = {"x": float(x), "y": float(y), "yaw": float(yaw)}
            self._save(data)
            return data

    def _nearest_lookup(self):
        """Per map pixel: coordinates of the nearest wall (cv2 distance transform).
        Makes every ICP nearest-neighbour search a vectorised array lookup."""
        if getattr(self, "_nn", None) is None:
            import cv2
            self._load()
            g = self._grid
            free = (g > 50).astype(np.uint8)                # walls = 0
            _, labels = cv2.distanceTransformWithLabels(free, cv2.DIST_L2, 5,
                                                        labelType=cv2.DIST_LABEL_PIXEL)
            rows, cols = np.nonzero(free == 0)
            # label ids follow the scan order of the zero pixels
            lab_ids = labels[rows, cols]
            lut = np.zeros((int(labels.max()) + 1, 2))
            res = self._meta["resolution"]
            ox, oy = self._meta["origin"][:2]
            h = g.shape[0]
            lut[lab_ids, 0] = ox + (cols + 0.5) * res
            lut[lab_ids, 1] = oy + (h - 1 - rows + 0.5) * res
            self._nn = (labels, lut)
        return self._nn

    def _icp_map(self, src: np.ndarray, init, iters: int = 60):
        labels, lut = self._nearest_lookup()
        res = self._meta["resolution"]
        ox, oy = self._meta["origin"][:2]
        h, w = labels.shape

        def nearest(pts):
            c = np.clip(np.floor((pts[:, 0] - ox) / res).astype(int), 0, w - 1)
            r = np.clip(np.floor(h - (pts[:, 1] - oy) / res).astype(int), 0, h - 1)
            q = lut[labels[r, c]]
            return q, np.hypot(q[:, 0] - pts[:, 0], q[:, 1] - pts[:, 1])

        T = np.array(init, dtype=float)
        for it in range(iters):
            reject = max(0.12, 0.8 * (1 - it / iters))
            moved = home_align.apply(T, src)
            q, d = nearest(moved)
            ok = d < reject
            if ok.sum() < 30:
                break
            a, b = moved[ok], q[ok]
            ca, cb = a.mean(axis=0), b.mean(axis=0)
            H = (a - ca).T @ (b - cb)
            dth = math.atan2(H[0, 1] - H[1, 0], H[0, 0] + H[1, 1])
            c, s_ = math.cos(dth), math.sin(dth)
            R = np.array([[c, -s_], [s_, c]])
            t = cb - R @ ca
            xy = R @ T[:2] + t
            T = np.array([xy[0], xy[1], T[2] + dth])
            if abs(dth) < 1e-6 and np.hypot(*t) < 1e-5 and it > 10:
                break
        _, d = nearest(home_align.apply(T, src))
        good = d < 0.10
        fit = float(good.mean()) if len(d) else 0.0
        rmse = float(np.sqrt(np.mean(d[good] ** 2))) if good.any() else float("inf")
        return (float(T[0]), float(T[1]), float(math.atan2(math.sin(T[2]), math.cos(T[2])))), fit, rmse

    def align_route(self, name: str) -> dict:
        """ICP of the route's HOME scan onto the map walls, started at the HOME pose
        (plus a few nearby guesses, because HOME is placed by hand)."""
        data = self.alignment()
        home = data.get("home")
        if not home:
            raise ValueError("Place HOME on the map first.")
        scan = home_align.load_home_scan(os.path.join(self.routes_dir, f"{name}.home.npz"))
        if scan is None or len(scan) < 100:
            raise ValueError(f"Route '{name}' has no HOME scan - re-record it.")
        if len(scan) > 4000:
            scan = scan[np.random.default_rng(0).choice(len(scan), 4000, replace=False)]
        hx, hy, hyaw = home["x"], home["y"], home["yaw"]
        best = None
        for dyaw_deg in (0, -8, 8, -16, 16, -25, 25):
            for dx, dy in ((0, 0), (0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5), (1.0, 0), (-1.0, 0), (0, 1.0), (0, -1.0)):
                T, fit, rmse = self._icp_map(scan, (hx + dx, hy + dy, hyaw + math.radians(dyaw_deg)))
                if best is None or fit > best[1] + 1e-6 or (abs(fit - best[1]) < 1e-6 and rmse < best[2]):
                    best = (T, fit, rmse)
        T, fit, rmse = best
        moved = math.hypot(T[0] - hx, T[1] - hy)
        result = {"tx": T[0], "ty": T[1], "theta": T[2], "fit": round(fit, 3), "rmse": round(rmse, 3),
                  "ok": fit >= 0.45, "home_offset_m": round(moved, 2)}
        with self._lock:
            data = self.alignment()
            data.setdefault("routes", {})[name] = result
            self._save(data)
        return result

    # ------------------------------------------------------------ routes
    def routes(self) -> list[dict]:
        data = self.alignment()
        home = data.get("home")
        out = []
        if not os.path.isdir(self.routes_dir):
            return out
        for fn in sorted(os.listdir(self.routes_dir)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.routes_dir, fn)) as f:
                    r = json.load(f)
            except (OSError, ValueError):
                continue
            name = r.get("name") or fn[:-5]
            al = data.get("routes", {}).get(name)
            if al and al.get("ok"):
                T, source = (al["tx"], al["ty"], al["theta"]), "scan"
            elif home:
                T, source = (home["x"], home["y"], home["yaw"]), "home"
            else:
                T, source = None, "none"
            pts = np.asarray(r.get("points") or [[0, 0, 0]], float)[:, :2]
            map_pts = home_align.apply(T, pts) if T is not None else None
            stops = []
            for st in r.get("stops", []):
                i = min(int(st.get("index", 0)), len(pts) - 1)
                p = map_pts[i] if map_pts is not None else None
                stops.append({"name": st.get("name"), "title_en": st.get("title_en"),
                              "title_de": st.get("title_de"), "text_en": st.get("text_en", ""),
                              "text_de": st.get("text_de", ""),
                              "map": [round(float(p[0]), 3), round(float(p[1]), 3)] if p is not None else None,
                              "yaw": (st.get("yaw", 0) + T[2]) if T is not None else None})
            length = float(np.sum(np.hypot(*np.diff(pts, axis=0).T))) if len(pts) > 1 else 0.0
            out.append({
                "name": name, "title_en": r.get("title_en", ""), "title_de": r.get("title_de", ""),
                "intro_en": r.get("arrival_en", ""), "intro_de": r.get("arrival_de", ""),
                "gesture_start": r.get("gesture_start", "high_wave"),
                "gesture_end": r.get("gesture_end", "face_wave"),
                "kind": "tour" if r.get("stops") else "route", "created": r.get("created", ""),
                "length_m": round(length, 1), "home_scan": os.path.isfile(
                    os.path.join(self.routes_dir, f"{name}.home.npz")),
                "alignment": {"source": source, **({k: al[k] for k in ("fit", "rmse", "ok")} if al else {})},
                "path": [[round(float(x), 3), round(float(y), 3)] for x, y in map_pts[::2]]
                if map_pts is not None else None,
                "stops": stops,
            })
        return out

    # ------------------------------------------------------------ editing (tour editor)
    TEXT_FIELDS = ("title_en", "title_de", "text_en", "text_de")
    TOUR_GESTURES = ("none", "high_wave", "face_wave", "clap", "heart", "two_hand_kiss")
    MAX_TEXT = 600

    def _route_path(self, name: str) -> str:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("Invalid route name.")
        path = os.path.join(self.routes_dir, f"{name}.json")
        if not os.path.isfile(path):
            raise KeyError(name)
        return path

    def _rewrite(self, path: str, data: dict) -> None:
        """Write in place (the route files may belong to root; they are chmod 666)."""
        text = json.dumps(data, indent=1, ensure_ascii=False)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except PermissionError:
            raise PermissionError(
                f"No write permission for {os.path.basename(path)}. On Ubuntu run: "
                f"sudo chmod 666 {path}")

    @classmethod
    def _clean(cls, value) -> str:
        v = str(value or "").strip()
        return v[: cls.MAX_TEXT]

    def update_route(self, name: str, fields: dict) -> dict:
        path = self._route_path(name)
        with self._lock:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            mapping = {"title_en": "title_en", "title_de": "title_de",
                       "intro_en": "arrival_en", "intro_de": "arrival_de"}
            for k, target in mapping.items():
                if k in fields and fields[k] is not None:
                    data[target] = self._clean(fields[k])
            for k in ("gesture_start", "gesture_end"):
                v = fields.get(k)
                if v is not None:
                    if v not in self.TOUR_GESTURES:
                        raise ValueError(f"Unknown gesture '{v}'.")
                    data[k] = v
            self._rewrite(path, data)
        return {"ok": True}

    def update_stop(self, name: str, stop: str, fields: dict) -> dict:
        path = self._route_path(name)
        with self._lock:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for st in data.get("stops", []):
                if st.get("name") == stop:
                    for k in self.TEXT_FIELDS:
                        if k in fields and fields[k] is not None:
                            st[k] = self._clean(fields[k])
                    self._rewrite(path, data)
                    return {"ok": True, "stop": st}
        raise KeyError(stop)

    def delete_stop(self, name: str, stop: str) -> dict:
        path = self._route_path(name)
        with self._lock:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            stops = data.get("stops", [])
            keep = [st for st in stops if st.get("name") != stop]
            if len(keep) == len(stops):
                raise KeyError(stop)
            data["stops"] = keep
            self._rewrite(path, data)
        return {"ok": True, "stops": len(keep)}

    # ------------------------------------------------------------ live pose
    def live_pose(self, guide_pose: dict | None) -> dict | None:
        if not guide_pose:
            return None
        data = self.alignment()
        home = data.get("home")
        route = guide_pose.get("route")
        al = data.get("routes", {}).get(route or "")
        if guide_pose.get("aligned") and al and al.get("ok"):
            p = apply_pose((al["tx"], al["ty"], al["theta"]), guide_pose["aligned"])
            src = "route"
        elif guide_pose.get("session") and home:
            p = apply_pose((home["x"], home["y"], home["yaw"]), guide_pose["session"])
            src = "home"
        else:
            return None
        return {"x": round(p[0], 3), "y": round(p[1], 3), "yaw": round(p[2], 4), "source": src,
                "age_s": guide_pose.get("age_s"), "route": route, "state": guide_pose.get("state")}


    def combine_live(self, gp: dict | None, lp: dict | None) -> dict:
        """Best G1 pose for the map: the map localizer (LiDAR matched to the map, works
        anywhere) when its quality is good/weak; otherwise the guide pose via HOME/route."""
        if lp and lp.get("map") and lp.get("quality") in ("good", "weak"):
            x, y, yaw = lp["map"]
            return {"pose": {"x": x, "y": y, "yaw": yaw, "source": "lidar_localizer",
                             "quality": lp["quality"], "age_s": lp.get("age_s"),
                             "route": (gp or {}).get("route"), "state": (gp or {}).get("state")},
                    "localizer": lp, "raw": gp}
        if gp is None:
            return {"pose": None, "detail": "Guide mode not running", "localizer": lp}
        return {"pose": self.live_pose(gp), "raw": gp, "localizer": lp}


def read_pgm(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        data = f.read()
    magic = data[:2]
    # parse header tokens skipping comments
    tokens, i = [], 2
    while len(tokens) < 3:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b"#":
            while data[i:i + 1] not in (b"\n", b""):
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        tokens.append(int(data[i:j]))
        i = j
    w, h, maxval = tokens
    i += 1
    if magic == b"P5":
        arr = np.frombuffer(data, np.uint8 if maxval < 256 else ">u2", count=w * h, offset=i)
    else:  # P2 ascii
        arr = np.array(data[i:].split(), dtype=np.int32)[: w * h]
    return arr.reshape(h, w).astype(np.uint8)


lab_map = LabMap()
