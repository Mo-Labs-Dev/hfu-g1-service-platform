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
import threading
import time
from dataclasses import dataclass, field

from route_core import (Follower, FollowParams, OdometryWatch, Route, SafetyError,
                        obstacle_points_in_box)

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
}


@dataclass
class GuideStatus:
    state: str = "idle"        # idle starting guiding blocked arrived returning done cancelled aborted
    route: str = ""
    progress: float = 0.0
    message: str = ""
    leg: str = ""              # "out" / "back"
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
                    "message": s.message, "leg": s.leg}

    def _say(self, key: str, lang: str, title: str = "", custom: str = "") -> None:
        text = custom or TEXT[key][lang].format(t=title)
        try:
            self.voice.say(text, lang)
        except Exception:
            pass                                    # speech must never block safety

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

    def run(self, route: Route, lang: str = "en", return_home: bool = True,
            wait_s: float = 20.0) -> str:
        """Blocking. Returns final state."""
        lang = lang if lang in ("en", "de") else "en"
        title = (route.title_de if lang == "de" else route.title_en) or route.name.replace("_", " ")
        self._cancel.clear()
        self._set(state="starting", route=route.name, progress=0.0, leg="out",
                  message="", started_at=self.clock())
        try:
            self.preflight()
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
            try:
                self.motion.end()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _wait(self, seconds: float) -> bool:
        end = self.clock() + seconds
        while self.clock() < end:
            if self._cancel.is_set():
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

    def _follow(self, route: Route, leg: str, lang: str, align_end: bool = False) -> str:
        f = Follower(route, self.p, align_end=align_end)
        watch = OdometryWatch(self.p)
        last_odom_t = None
        blocked_since = None
        last_excuse = -1e9
        self._set(state="guiding" if leg == "out" else "returning", leg=leg, message="")
        while True:
            if self._cancel.is_set():
                self.motion.send(0.0, 0.0)
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

            obstacles = obstacle_points_in_box(self.sensors.points(), (x, y, z), yaw,
                                               self.p, turning=f.turning)
            cmd = f.step(x, y, yaw, obstacles)

            if cmd.state == "arrived":
                self.motion.send(0.0, 0.0)
                return "arrived"
            if cmd.state == "blocked":
                blocked_since = blocked_since or now
                waited = now - blocked_since
                self._set(state="blocked", progress=cmd.progress,
                          message=f"Waiting for the way to clear ({waited:.0f} s)")
                if waited > 6 and now - last_excuse > 20:
                    self._say("blocked", lang)
                    last_excuse = now
                if waited > 90:
                    raise SafetyError("Path blocked for more than 90 s.")
            else:
                if blocked_since is not None:
                    self._set(state="guiding" if leg == "out" else "returning", message="")
                blocked_since = None
                with self._lock:
                    self.status.progress = cmd.progress
            self.motion.send(cmd.x, cmd.yaw)
            self.sleep(self.period)
