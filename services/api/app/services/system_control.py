"""
Start / stop robot services from G1 Studio (replaces the terminal commands).

Only a fixed list of actions exists, each runs one of the g1_daily scripts or a
fixed docker command. Every action needs the operator PIN (~/.g1_teleop_pin).
One action at a time; the output is kept for the Studio log panel.
"""
from __future__ import annotations

import hmac
import os
import subprocess
import threading
import time
from collections import deque

DAILY_DIR = os.path.expanduser(os.getenv("G1_DAILY_DIR", "~/Documents/Projekte/g1pilot-main/g1_daily"))
PIN_FILE = os.path.expanduser(os.getenv("G1_TELEOP_PIN_FILE", "~/.g1_teleop_pin"))
CONTAINER = os.getenv("G1_CONTAINER", "g1pilot-dev")


def _script(name: str, *args: str) -> list[str]:
    return ["bash", os.path.join(DAILY_DIR, name), *args]


def _docker_pkill(pattern: str, sig: str = "-INT") -> list[str]:
    return ["docker", "exec", CONTAINER, "pkill", sig, "-f", pattern]


# id -> (label, description, needs_home_confirmation, steps)
ACTIONS: dict[str, tuple[str, str, bool, list[list[str]]]] = {
    "start_all": ("Start app services",
                  "Voice, camera, status, teleop and backend (skips what already runs).",
                  False, [_script("g1_start_all.sh")]),
    "start_guide": ("Start guide mode",
                    "LiDAR + FAST-LIO + guide service. G1 must stand on HOME in walking mode.",
                    True, [_script("g1_start_guide.sh", "--yes")]),
    "stop_guide": ("Stop guide mode", "Stops guide service, FAST-LIO and the LiDAR driver.",
                   False, [_script("g1_stop_guide.sh")]),
    "restart_guide": ("Restart guide mode",
                      "Stop + start guide mode. Use after a G1 restart or a FAST-LIO problem.",
                      True, [_script("g1_stop_guide.sh"), _script("g1_start_guide.sh", "--yes")]),
    "restart_camera": ("Restart camera bridge", "Use when the camera shows no frames.",
                       False, [_docker_pkill("g1_camera_bridge.py", "-TERM"), ["sleep", "2"],
                               _script("g1_start_all.sh")]),
    "restart_teleop": ("Restart teleop server",
                       "Use after a G1 restart (FSM unknown). G1 must stand still. Unlock the app again.",
                       False, [_docker_pkill("run_teleop_server.py"), ["sleep", "3"],
                               _script("g1_start_all.sh")]),
}


class SystemControl:
    def __init__(self):
        self._lock = threading.Lock()
        self.running: str | None = None
        self.last: dict = {}
        self.output: deque[str] = deque(maxlen=400)
        self._fails = 0
        self._locked_until = 0.0

    # ---------------------------------------------------------- PIN
    def check_pin(self, pin: str) -> None:
        now = time.monotonic()
        if now < self._locked_until:
            raise PermissionError(f"Too many wrong PINs - wait {int(self._locked_until - now)} s.")
        try:
            with open(PIN_FILE) as f:
                expected = f.read().strip()
        except OSError:
            raise PermissionError("PIN file missing on the robot PC (~/.g1_teleop_pin).")
        if not expected or not hmac.compare_digest(str(pin or "").strip(), expected):
            self._fails += 1
            if self._fails >= 5:
                self._fails, self._locked_until = 0, now + 60
            raise PermissionError("Wrong PIN.")
        self._fails = 0

    # ---------------------------------------------------------- actions
    def list(self) -> list[dict]:
        return [{"id": k, "label": v[0], "description": v[1], "confirm_home": v[2]}
                for k, v in ACTIONS.items()]

    def status(self) -> dict:
        return {"running": self.running, "last": self.last, "output": list(self.output)[-120:]}

    def start(self, action: str, pin: str, home_confirmed: bool) -> dict:
        if action not in ACTIONS:
            raise KeyError(action)
        self.check_pin(pin)
        label, _, need_home, steps = ACTIONS[action]
        if need_home and not home_confirmed:
            raise ValueError("Confirm that G1 stands on the HOME tape in walking mode.")
        with self._lock:
            if self.running:
                raise RuntimeError(f"'{ACTIONS[self.running][0]}' is still running.")
            self.running = action
        threading.Thread(target=self._run, args=(action, label, steps), daemon=True).start()
        return self.status()

    def _run(self, action: str, label: str, steps: list[list[str]]) -> None:
        t0 = time.time()
        self.output.append(f"===== {time.strftime('%H:%M:%S')}  {label} =====")
        rc = 0
        env = dict(os.environ, G1_ASSUME_HOME="1", TERM="dumb")
        try:
            for cmd in steps:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, env=env)
                for line in p.stdout:  # type: ignore[union-attr]
                    line = line.rstrip()
                    for code in ("\x1b[0;32m", "\x1b[1;33m", "\x1b[0;31m", "\x1b[0m", "\x1b[1m"):
                        line = line.replace(code, "")
                    if line:
                        self.output.append(line)
                rc = p.wait(timeout=300)
                if rc != 0 and cmd[0] != "docker":      # pkill returns 1 if nothing matched
                    break
        except Exception as exc:
            rc = -1
            self.output.append(f"ERROR: {exc}")
        finally:
            ok = rc == 0
            self.last = {"action": action, "label": label, "ok": ok, "rc": rc,
                         "seconds": round(time.time() - t0, 1), "finished": time.strftime("%H:%M:%S")}
            self.output.append(f"----- {'done' if ok else 'FAILED'} ({self.last['seconds']} s)")
            self.running = None


system_control = SystemControl()
