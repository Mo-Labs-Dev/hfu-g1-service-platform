"""
GuideRunner: executes one guided walk (route out, announce, wait, route back).

All hardware access goes through three small interfaces so it can be tested
in simulation:
  motion  - send(x, yaw), stop(), status() -> teleop server status dict
  sensors - pose() -> (t, x, y, z, yaw) or None, points() -> Nx3 or None
  voice   - say(text, lang)
"""
from __future__ import annotations

import math

import numpy as np
import threading
import time
from dataclasses import dataclass, field

from home_align import AlignedSensors, align, slice_2d
from route_core import (Follower, FollowParams, OdometryWatch, Route, SafetyError,
                        obstacle_points_in_box, obstacle_points_on_path)

TEXT = {
    "start": {"en": "Please follow me. I will take you to the {t}.",
              "de": "Bitte folgen Sie mir. Ich bringe Sie zu: {t}."},
    "arrive": {"en": "Here is the {t}.", "de": "Wir sind da: {t}."},
    "blocked": {"en": "Excuse me, please let me pass.",
                "de": "Entschuldigung, darf ich bitte vorbei?"},
    "back": {"en": "I am going back now. Goodbye!",
             "de": "Ich gehe jetzt zurück. Auf Wiedersehen!"},
    "abort": {"en": "I have to stop here. Please ask our team for help.",
              "de": "Ich muss hier anhalten. Bitte fragen Sie unser Team."},
    # Lab tour
    "tour_start": {"en": "Welcome to the {t}! Please follow me, I will show you our lab.",
                   "de": "Willkommen zur {t}! Bitte folgen Sie mir, ich zeige Ihnen unser Labor."},
    "stop": {"en": "Here you can see the {t}.", "de": "Hier sehen Sie: {t}."},
    "next": {"en": "Let's continue. Please follow me.",
             "de": "Weiter geht's. Bitte folgen Sie mir."},
    "tour_end": {"en": "That was our lab tour. Thank you for visiting, and have a nice day!",
                 "de": "Das war unsere Laborführung. Vielen Dank für Ihren Besuch und einen schönen Tag!"},
}


@dataclass
class GuideStatus:
    state: str = "idle"        # idle starting guiding blocked arrived returning done cancelled aborted
    route: str = ""
    progress: float = 0.0
    message: str = ""
    leg: str = ""              # "out" / "back" / "tour"
    kind: str = "route"        # "route" / "tour"
    stop_index: int = 0        # tour: 1..stop_count while at / walking to a stop
    stop_count: int = 0
    stop_title: str = ""
    alignment: dict = field(default_factory=dict)   # HOME alignment result (for logs / thesis)
    started_at: float = 0.0
    history: list = field(default_factory=list)


class GuideRunner:
    def __init__(self, motion, sensors, voice, params: FollowParams | None = None,
                 clock=time.monotonic, sleep=time.sleep, rate_hz: float = 10.0):
        self.motion = motion
        self.sensors = sensors
        self.voice = voice
        self.p = params or FollowParams()
        self.clock = clock
        self.sleep = sleep
        self.period = 1.0 / rate_hz
        self.status = GuideStatus()
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self.status, k, v)
            if "state" in kw:
                self.status.history.append((round(self.clock(), 2), kw["state"], kw.get("message", "")))

    def snapshot(self) -> dict:
        with self._lock:
            s = self.status
            return {"state": s.state, "route": s.route, "progress": round(s.progress, 3),
                    "message": s.message, "leg": s.leg, "kind": s.kind,
                    "stop_index": s.stop_index, "stop_count": s.stop_count,
                    "stop_title": s.stop_title, "alignment": dict(s.alignment)}

    def _say(self, key: str, lang: str, title: str = "", custom: str = "") -> float:
        """Speak; returns roughly how many seconds until the speech is over."""
        text = custom or TEXT[key][lang].format(t=title)
        estimate = 1.0 + len(text.split()) / 2.3
        try:
            res = self.voice.say(text, lang)
            if isinstance(res, dict) and res.get("ends_in_ms") is not None:
                return float(res["ends_in_ms"]) / 1000.0 + 0.5
        except Exception:
            pass                                    # speech must never block safety
        return estimate

    def _hush(self) -> None:
        try:
            if hasattr(self.voice, "stop"):
                self.voice.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def preflight(self) -> dict:
        st = self.motion.status()
        if st.get("estop"):
            raise SafetyError("Software E-stop is active.")
        if st.get("fsm_id") != 500:
            raise SafetyError(f"Robot is not in walking mode (FSM {st.get('fsm_id')}).")
        if st.get("teleop_active"):
            raise SafetyError(f"Robot is controlled by '{st.get('operator')}' - lock the joystick first.")
        if st.get("gesture"):
            raise SafetyError("A gesture is running.")
        pose = self.sensors.pose()
        if pose is None or self.clock() - pose[0] > self.p.odom_pause_age:
            raise SafetyError("No live FAST-LIO odometry.")
        return st

    # ------------------------------------------------------------------
    ALIGN_SECONDS = 2.5
    ALIGN_MIN_FIT = 0.45
    ALIGN_MAX_SHIFT = 1.0          # m
    ALIGN_MAX_TURN_DEG = 20.0

    def _align_home(self, route: Route) -> None:
        """Compare today's LiDAR view at HOME with the one saved while teaching and
        switch to the teaching frame. Routes without a HOME scan run unchanged."""
        home_xy = getattr(route, "home_xy", None)
        self.status.alignment = {}
        if home_xy is None or len(home_xy) < 100:
            self.status.alignment = {"used": False, "reason": "route has no HOME scan"}
            return
        self._set(message="Checking my position at HOME ...")
        clouds, last_id = [], None
        end = self.clock() + self.ALIGN_SECONDS
        while self.clock() < end:
            pts = self._raw_sensors.points()
            if pts is not None and id(pts) != last_id and len(pts):
                clouds.append(pts)
                last_id = id(pts)
            self.sleep(0.1)
        pose = self._raw_sensors.pose()
        cur = slice_2d(np.concatenate(clouds) if clouds else None, self.p.lidar_height,
                       origin_xy=(pose[1], pose[2]) if pose else (0.0, 0.0))
        if len(cur) < 100:
            raise SafetyError("HOME check failed: too few LiDAR points (is FAST-LIO running?).")
        T, fit, rmse = align(cur, home_xy)
        shift, turn = math.hypot(T[0], T[1]), math.degrees(T[2])
        self.status.alignment = {"used": True, "dx": round(T[0], 3), "dy": round(T[1], 3),
                                 "dyaw_deg": round(turn, 2), "fit": round(fit, 3),
                                 "rmse": round(rmse, 3)}
        if fit < self.ALIGN_MIN_FIT or shift > self.ALIGN_MAX_SHIFT or abs(turn) > self.ALIGN_MAX_TURN_DEG:
            raise SafetyError(
                f"HOME check failed (match {fit:.0%}, {shift:.2f} m, {turn:+.1f} deg). "
                "Place G1 on the HOME tape and restart guide mode.")
        self.sensors = AlignedSensors(self._raw_sensors, T)

    def run(self, route: Route, lang: str = "en", return_home: bool = True,
            wait_s: float = 20.0) -> str:
        """Blocking. Returns final state. Every run is written to the run log
        (self.run_logger, set by the guide service) for G1 Studio / the thesis."""
        t_wall, t0 = time.time(), self.clock()
        self._blocked_events = []
        h0 = len(self.status.history)
        result = "error"
        try:
            result = self._run_impl(route, lang, return_home, wait_s)
            return result
        finally:
            self._log_run(route, lang, return_home, result, t_wall, t0, h0)

    def _log_run(self, route, lang, return_home, result, t_wall, t0, h0) -> None:
        logger = getattr(self, "run_logger", None)
        if logger is None:
            return
        hist = self.status.history[h0:]
        blocked_s, since = 0.0, None
        for t, state, _msg in hist:
            if state == "blocked" and since is None:
                since = t
            elif state != "blocked" and since is not None:
                blocked_s += t - since
                since = None
        if since is not None:
            blocked_s += self.clock() - since
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route.points, route.points[1:]))
        record = {
            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t_wall)),
            "route": route.name, "kind": "tour" if route.stops else "route", "lang": lang,
            "return_home": bool(return_home), "result": result,
            "duration_s": round(self.clock() - t0, 1), "length_m": round(length, 1),
            "stops": len(route.stops), "progress": round(self.status.progress, 3),
            "blocked_count": len(self._blocked_events), "blocked_s": round(blocked_s, 1),
            "blocked_at": self._blocked_events[:50], "message": self.status.message,
            "alignment": dict(self.status.alignment or {}),
        }
        try:
            logger(record)
        except Exception as exc:                      # logging must never break guiding
            print(f"[guide] run log failed: {exc}")

    def _run_impl(self, route: Route, lang: str = "en", return_home: bool = True,
                  wait_s: float = 20.0) -> str:
        lang = lang if lang in ("en", "de") else "en"
        if route.stops:
            return self.run_tour(route, lang, return_home=return_home)
        title = (route.title_de if lang == "de" else route.title_en) or route.name.replace("_", " ")
        self._cancel.clear()
        self._set(state="starting", route=route.name, progress=0.0, leg="out",
                  message="", started_at=self.clock(), kind="route",
                  stop_index=0, stop_count=0, stop_title="")
        self._raw_sensors = self.sensors
        try:
            self.preflight()
            self._align_home(route)
            pose = self.sensors.pose()
            Follower(route, self.p).check_start(pose[1], pose[2], pose[4])
            self.motion.begin()
            self._say("start", lang, title)
            result = self._follow(route, leg="out", lang=lang)
            if result != "arrived":
                return result
            arrival = route.arrival_de if lang == "de" else route.arrival_en
            self._set(state="arrived", progress=1.0, message=f"Arrived: {title}")
            self._say("arrive", lang, title, custom=arrival)
            if not return_home:
                self._set(state="done")
                return "done"
            if not self._wait(wait_s):
                return self.status.state
            self._say("back", lang)
            result = self._follow(route.reversed(), leg="back", lang=lang, align_end=True)
            if result == "arrived":
                self._set(state="done", progress=1.0, message="Back home")
                return "done"
            return result
        except SafetyError as exc:
            self._set(state="aborted", message=str(exc))
            self._say("abort", lang)
            return "aborted"
        finally:
            self.sensors = self._raw_sensors
            try:
                self.motion.end()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def run_tour(self, route: Route, lang: str = "en", return_home: bool = True,
                 stop_pause_s: float = 3.0) -> str:
        """Lab tour: walk the taught tour, stop at every marked stop, turn to the
        exhibit, explain it, continue. A tour taught as a loop ends at HOME by
        itself; otherwise G1 walks the whole route back."""
        lang = lang if lang in ("en", "de") else "en"
        de = lang == "de"
        title = (route.title_de if de else route.title_en) or route.name.replace("_", " ")
        stops = sorted(route.stops, key=lambda st: st["index"])
        n = len(stops)
        last = len(route.points) - 1
        cum = [0.0]
        for a, b in zip(route.points, route.points[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        total = cum[-1] or 1.0
        self._cancel.clear()
        self._set(state="starting", route=route.name, progress=0.0, leg="tour", kind="tour",
                  message="", started_at=self.clock(), stop_index=0, stop_count=n, stop_title="")
        self._raw_sensors = self.sensors
        try:
            self.preflight()
            self._align_home(route)
            pose = self.sensors.pose()
            Follower(route, self.p).check_start(pose[1], pose[2], pose[4])
            self.motion.begin()
            say_s = self._say("tour_start", lang, title, custom=(route.arrival_de if de else route.arrival_en) or "")
            if not self._wait(min(say_s, 8.0)):
                return self.status.state
            i0 = 0
            for k, st in enumerate(stops, start=1):
                st_title = (st.get("title_de") if de else st.get("title_en")) or st.get("name", "").replace("_", " ")
                self._set(state="guiding", stop_index=k, stop_title=st_title,
                          message=f"Walking to stop {k}/{n}: {st_title}")
                if st["index"] > i0:
                    seg = route.segment(i0, st["index"], end_yaw=st.get("yaw"), name=f"{route.name}_stop{k}")
                    result = self._follow(seg, leg="tour", lang=lang, align_end=st.get("yaw") is not None,
                                          progress0=cum[i0] / total,
                                          progress_span=(cum[st["index"]] - cum[i0]) / total)
                    if result != "arrived":
                        return result
                self._set(state="explaining", progress=cum[st["index"]] / total,
                          message=f"Stop {k}/{n}: {st_title}")
                text = st.get("text_de") if de else st.get("text_en")
                say_s = self._say("stop", lang, st_title, custom=text or "")
                if not self._wait(say_s + stop_pause_s):
                    return self.status.state
                i0 = st["index"]
                if k < n or i0 < last - 1:
                    self._say("next", lang)
            # Last leg: to the end of the taught tour.
            if i0 < last - 1:
                self._set(state="guiding", stop_index=n, stop_title="", message="Last part of the tour")
                seg = route.segment(i0, last, name=f"{route.name}_end")
                result = self._follow(seg, leg="tour", lang=lang, align_end=route.is_loop,
                                      progress0=cum[i0] / total, progress_span=(total - cum[i0]) / total)
                if result != "arrived":
                    return result
            if route.is_loop or not return_home:
                self._say("tour_end", lang)
                self._set(state="done", progress=1.0, message="Tour finished" + (" - back home" if route.is_loop else ""))
                return "done"
            self._say("tour_end", lang)
            self._set(state="returning", stop_title="", message="Going back home")
            result = self._follow(route.reversed(), leg="back", lang=lang, align_end=True)
            if result == "arrived":
                self._set(state="done", progress=1.0, message="Back home")
                return "done"
            return result
        except SafetyError as exc:
            self._hush()
            self._set(state="aborted", message=str(exc))
            self._say("abort", lang)
            return "aborted"
        finally:
            self.sensors = self._raw_sensors
            try:
                self.motion.end()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _wait(self, seconds: float) -> bool:
        end = self.clock() + seconds
        while self.clock() < end:
            if self._cancel.is_set():
                self._hush()
                self._set(state="cancelled", message="Cancelled by operator")
                return False
            self.motion.send(0.0, 0.0)              # keep the lease alive
            self._check_operator()
            self.sleep(self.period)
        return True

    def _check_operator(self) -> None:
        st = self.motion.status()
        if st.get("estop"):
            raise SafetyError("Stopped: software E-stop.")
        if self.motion.stopped_by_operator():
            raise SafetyError("Stopped by operator (STOP button).")
        if st.get("fsm_id") not in (None, 500):
            raise SafetyError(f"Robot left walking mode (FSM {st.get('fsm_id')}).")

    def _follow(self, route: Route, leg: str, lang: str, align_end: bool = False,
                progress0: float = 0.0, progress_span: float = 1.0) -> str:
        f = Follower(route, self.p, align_end=align_end)
        watch = OdometryWatch(self.p)
        last_odom_t = None
        blocked_since = None
        last_excuse = -1e9
        moving = "returning" if leg == "back" else "guiding"
        if self.status.state != moving:
            self._set(state=moving, leg=leg, **({} if leg == "tour" else {"message": ""}))
        else:
            with self._lock:
                self.status.leg = leg
        while True:
            if self._cancel.is_set():
                self.motion.send(0.0, 0.0)
                self._hush()
                self._set(state="cancelled", message="Cancelled by operator")
                return "cancelled"
            self._check_operator()

            pose = self.sensors.pose()
            now = self.clock()
            if pose is None or now - pose[0] > self.p.odom_abort_age:
                raise SafetyError("Lost FAST-LIO odometry.")
            if now - pose[0] > self.p.odom_pause_age:
                self.motion.send(0.0, 0.0)
                self.sleep(self.period)
                continue
            t, x, y, z, yaw = pose
            if t != last_odom_t:
                watch.update(t, x, y, z)
                last_odom_t = t

            pts = self.sensors.points()
            if f.turning:
                obstacles = obstacle_points_in_box(pts, (x, y, z), yaw, self.p, turning=True)
            else:
                obstacles = obstacle_points_on_path(pts, (x, y, z), yaw, f.path_ahead(), self.p)
            cmd = f.step(x, y, yaw, obstacles)

            if cmd.state == "arrived":
                self.motion.send(0.0, 0.0)
                return "arrived"
            if cmd.state == "blocked":
                if blocked_since is None:
                    events = getattr(self, "_blocked_events", None)
                    if events is not None:
                        events.append([round(x, 2), round(y, 2)])     # teaching frame of the route
                blocked_since = blocked_since or now
                waited = now - blocked_since
                self._set(state="blocked", progress=progress0 + progress_span * cmd.progress,
                          message=f"Waiting for the way to clear ({waited:.0f} s)")
                if waited > 6 and now - last_excuse > 20:
                    self._say("blocked", lang)
                    last_excuse = now
                if waited > 90:
                    raise SafetyError("Path blocked for more than 90 s.")
            else:
                if blocked_since is not None:
                    self._set(state=moving, message="")
                blocked_since = None
                with self._lock:
                    self.status.progress = progress0 + progress_span * cmd.progress
            self.motion.send(cmd.x, cmd.yaw)
            self.sleep(self.period)
