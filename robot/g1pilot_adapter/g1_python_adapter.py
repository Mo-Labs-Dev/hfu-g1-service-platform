from __future__ import annotations

import math
import time
from dataclasses import dataclass

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient


@dataclass(frozen=True)
class MotionLimits:
    max_linear_speed: float = 0.30
    max_lateral_speed: float = 0.20
    max_yaw_speed: float = 0.30
    max_duration: float = 3.0


class G1PythonAdapter:
    FSM_LOCOMOTION = 500

    def __init__(
        self,
        interface: str = "enP2p1s0",
        limits: MotionLimits | None = None,
    ) -> None:
        self.interface = interface
        self.limits = limits or MotionLimits()

        ChannelFactoryInitialize(0, self.interface)

        self.client = LocoClient()
        self.client.SetTimeout(10.0)
        self.client.Init()

    def get_fsm_id(self) -> int:
        code, fsm_id = self.client.GetFsmId()

        self._check_response(code, "GetFsmId")

        if fsm_id is None:
            raise RuntimeError("GetFsmId returned no FSM value")

        return int(fsm_id)

    def is_locomotion_ready(self) -> bool:
        return self.get_fsm_id() == self.FSM_LOCOMOTION

    @staticmethod
    def _check_response(code: int, operation: str) -> None:
        if code != 0:
            raise RuntimeError(
                f"{operation} failed with SDK response code {code}"
            )

    @staticmethod
    def _validate_number(
        value: float,
        name: str,
        maximum: float,
    ) -> float:
        value = float(value)

        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")

        if abs(value) > maximum:
            raise ValueError(
                f"{name}={value} exceeds permitted range "
                f"[-{maximum}, {maximum}]"
            )

        return value

    def _require_locomotion_ready(self) -> None:
        fsm_id = self.get_fsm_id()

        if fsm_id != self.FSM_LOCOMOTION:
            raise RuntimeError(
                f"Movement blocked: expected FSM 500, got {fsm_id}"
            )

    def stop(self) -> None:
        # StopMove() in the SDK discards the response code.
        # Call SetVelocity directly so acceptance can be checked.
        code = self.client.SetVelocity(
            0.0,
            0.0,
            0.0,
            1.0,
        )

        self._check_response(code, "Stop velocity request")

        print(
            "[G1] Zero-velocity command accepted. "
            "Physical stop must be verified independently."
        )

    def move(
        self,
        vx: float = 0.0,
        vy: float = 0.0,
        yaw: float = 0.0,
        duration: float = 1.0,
    ) -> None:
        vx = self._validate_number(
            vx, "vx", self.limits.max_linear_speed
        )
        vy = self._validate_number(
            vy, "vy", self.limits.max_lateral_speed
        )
        yaw = self._validate_number(
            yaw, "yaw", self.limits.max_yaw_speed
        )

        duration = float(duration)

        if not math.isfinite(duration):
            raise ValueError("duration must be finite")

        if not 0.1 <= duration <= self.limits.max_duration:
            raise ValueError(
                f"duration must be between 0.1 and "
                f"{self.limits.max_duration} seconds"
            )

        self._require_locomotion_ready()

        print(
            f"[G1] Requesting velocity: "
            f"vx={vx:.3f}, vy={vy:.3f}, "
            f"yaw={yaw:.3f}, duration={duration:.2f}s"
        )

        movement_error = None

        try:
            code = self.client.SetVelocity(
                vx,
                vy,
                yaw,
                duration,
            )

            self._check_response(code, "SetVelocity")

            print(
                "[G1] Motion command accepted. "
                "Actual displacement is not verified."
            )

            time.sleep(duration)

        except BaseException as exc:
            movement_error = exc
            raise

        finally:
            try:
                self.stop()
            except Exception as stop_error:
                print(
                    "[G1] WARNING: Zero-velocity request "
                    f"failed: {stop_error}. "
                    "Use the approved physical safety procedure."
                )

                if movement_error is None:
                    raise

    def forward(
        self,
        speed: float = 0.20,
        duration: float = 1.0,
    ) -> None:
        self.move(vx=abs(speed), duration=duration)

    def backward(
        self,
        speed: float = 0.15,
        duration: float = 1.0,
    ) -> None:
        self.move(vx=-abs(speed), duration=duration)

    def left(
        self,
        speed: float = 0.10,
        duration: float = 1.0,
    ) -> None:
        self.move(vy=abs(speed), duration=duration)

    def right(
        self,
        speed: float = 0.10,
        duration: float = 1.0,
    ) -> None:
        self.move(vy=-abs(speed), duration=duration)

    def turn_left(
        self,
        speed: float = 0.20,
        duration: float = 1.0,
    ) -> None:
        self.move(yaw=abs(speed), duration=duration)

    def turn_right(
        self,
        speed: float = 0.20,
        duration: float = 1.0,
    ) -> None:
        self.move(yaw=-abs(speed), duration=duration)


if __name__ == "__main__":
    robot = G1PythonAdapter()

    print("Current FSM:", robot.get_fsm_id())
    print("Locomotion ready:", robot.is_locomotion_ready())
    print("No movement command issued.")