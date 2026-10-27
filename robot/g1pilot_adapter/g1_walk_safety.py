import math
import threading
import time


class G1WalkSafety:
    MAX_VX = 0.10
    MAX_VY = 0.05
    MAX_YAW = 0.15
    COMMAND_TIMEOUT = 0.30

    def __init__(self, send_velocity):
        self.send_velocity = send_velocity
        self.lock = threading.RLock()
        self.armed = False
        self.fault = False
        self.last_command = 0.0
        self.deadline = 0.0
        self.generation = 0

    def arm(self, confirmed=False):
        with self.lock:
            if not confirmed or self.fault:
                return False
            self.armed = True
            self.last_command = time.monotonic()
            self.deadline = self.last_command + self.COMMAND_TIMEOUT
            self.generation += 1
            return True

    def command(self, vx, vy, yaw):
        values = (vx, vy, yaw)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Non-finite velocity")

        if (
            abs(vx) > self.MAX_VX
            or abs(vy) > self.MAX_VY
            or abs(yaw) > self.MAX_YAW
        ):
            raise ValueError("Velocity exceeds safety limits")

        with self.lock:
            if not self.armed or self.fault:
                raise RuntimeError("Walking controller not armed")

            if time.monotonic() > self.deadline:
                self.armed = False
                self.fault = True
                raise RuntimeError("Walking command expired")

            self.last_command = time.monotonic()
            self.deadline = self.last_command + self.COMMAND_TIMEOUT

            self.send_velocity(vx, vy, yaw)

    def stop(self):
        with self.lock:
            self.armed = False
            self.generation += 1
            self.send_velocity(0.0, 0.0, 0.0)

    def watchdog(self):
        while True:
            time.sleep(0.02)

            with self.lock:
                expired = (
                    self.armed
                    and time.monotonic() > self.deadline
                )

                if expired:
                    self.armed = False
                    self.fault = True
                    self.generation += 1
                    self.send_velocity(0.0, 0.0, 0.0)
