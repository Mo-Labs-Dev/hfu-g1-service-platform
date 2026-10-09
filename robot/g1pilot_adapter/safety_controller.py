from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional


API_GET_FSM_ID = 7001
API_GET_FSM_MODE = 7002


@dataclass
class RobotState:
    fsm_id: Optional[int]
    fsm_mode: Optional[int]
    connected: bool


class SafetyController:
    """
    Safety boundary between the thesis software and G1Pilot/Unitree SDK.

    Important:
    - Frontends must never call Unitree locomotion methods directly.
    - Physical E-stop remains the primary emergency safety mechanism.
    - Unvalidated state transitions are intentionally not implemented here.
    """

    def __init__(self, robot):
        self.robot = robot

    def _read_int(self, api_id: int) -> Optional[int]:
        try:
            code, data = self.robot._Call(api_id, "")

            if code != 0 or data is None:
                return None

            payload = json.loads(data)
            value = payload.get("data")

            if value is None:
                return None

            return int(value)

        except Exception:
            return None

    def get_state(self) -> RobotState:
        fsm_id = self._read_int(API_GET_FSM_ID)
        fsm_mode = self._read_int(API_GET_FSM_MODE)

        connected = fsm_id is not None and fsm_mode is not None

        return RobotState(
            fsm_id=fsm_id,
            fsm_mode=fsm_mode,
            connected=connected,
        )

    def print_state(self) -> RobotState:
        state = self.get_state()

        print("\n--- SAFETY STATUS ---")
        print(f"Connected : {state.connected}")
        print(f"FSM ID    : {state.fsm_id}")
        print(f"FSM Mode  : {state.fsm_mode}")
        print("---------------------\n")

        return state

    def stop_motion(self) -> None:
        """
        Normal locomotion stop.

        This requests zero velocity. It is NOT a replacement
        for the physical emergency stop.
        """

        state = self.get_state()

        if not state.connected:
            raise RuntimeError(
                "Robot state unavailable. Stop command not sent."
            )

        code = self.robot.SetVelocity(
            0.0,
            0.0,
            0.0,
            1.0,
        )

        if code != 0:
            raise RuntimeError(
                f"Stop command failed with RPC code {code}."
            )

        print("[SafetyController] Zero-velocity stop sent.")

    def damp(self, confirmed: bool = False) -> None:
        """
        Request Unitree Damp state.

        Caller must explicitly confirm the operation.
        """

        if not confirmed:
            raise RuntimeError(
                "Damp rejected: explicit confirmation required."
            )

        state = self.get_state()

        if not state.connected:
            raise RuntimeError(
                "Robot state unavailable. Damp command not sent."
            )

        print("[SafetyController] Requesting Damp state.")

        self.robot.Damp()

        print(
            "[SafetyController] Damp request sent. "
            "Verify robot state before further commands."
        )

    def start_robot(self) -> None:
        raise RuntimeError(
            "START LOCKED: startup/balancing sequence "
            "has not yet been validated."
        )

    def move(self, vx: float, vy: float, yaw: float) -> None:
        raise RuntimeError(
            "MOVEMENT LOCKED: locomotion has not yet been validated."
        )
