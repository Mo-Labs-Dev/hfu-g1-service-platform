from __future__ import annotations

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

        if code != 0:
            raise RuntimeError(f"GetFsmId failed with code {code}")

        if fsm_id is None:
            raise RuntimeError("GetFsmId returned no FSM value")

        return int(fsm_id)

    def is_locomotion_ready(self) -> bool:
        return self.get_fsm_id() == self.FSM_LOCOMOTION

    def stop(self) -> None:
        self.client.StopMove()

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _require_locomotion_ready(self) -> None:
        fsm_id = self.get_fsm_id()

        if fsm_id != self.FSM_LOCOMOTION:
            raise RuntimeError(
                f"Movement blocked: expected FSM 500, got {fsm_id}"
            )

    def move(
        self,
        vx: float = 0.0,
        vy: float = 0.0,
        yaw: float = 0.0,
        duration: float = 1.0,
    ) -> None:
        self._require_locomotion_ready()

        vx = self._clamp(
            vx,
            -self.limits.max_linear_speed,
            self.limits.max_linear_speed,
        )

        vy = self._clamp(
            vy,
            -self.limits.max_lateral_speed,
            self.limits.max_lateral_speed,
        )

        yaw = self._clamp(
            yaw,
            -self.limits.max_yaw_speed,
            self.limits.max_yaw_speed,
        )

        duration = self._clamp(
            duration,
            0.1,
            self.limits.max_duration,
        )

        try:
            self.client.SetVelocity(
                float(vx),
                float(vy),
                float(yaw),
                float(duration),
            )
            time.sleep(duration)

        finally:
            self.stop()

    def forward(self, speed: float = 0.20, duration: float = 1.0) -> None:
        self.move(vx=abs(speed), duration=duration)

    def backward(self, speed: float = 0.15, duration: float = 1.0) -> None:
        self.move(vx=-abs(speed), duration=duration)

    def left(self, speed: float = 0.10, duration: float = 1.0) -> None:
        self.move(vy=abs(speed), duration=duration)

    def right(self, speed: float = 0.10, duration: float = 1.0) -> None:
        self.move(vy=-abs(speed), duration=duration)

    def turn_left(self, speed: float = 0.20, duration: float = 1.0) -> None:
        self.move(yaw=abs(speed), duration=duration)

    def turn_right(self, speed: float = 0.20, duration: float = 1.0) -> None:
        self.move(yaw=-abs(speed), duration=duration)


if __name__ == "__main__":
    robot = G1PythonAdapter()

    print("Current FSM:", robot.get_fsm_id())
    print("Locomotion ready:", robot.is_locomotion_ready())
