from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Protocol

# Unitree G1 FSM ids (validated on Day 01 / Day 02).
FSM_ZERO_TORQUE = 0
FSM_DAMP = 1
FSM_STAND_UP = 4
FSM_LOCOMOTION = 500

# Raw RPC api ids, used when the SDK has no GetFsmId()/GetFsmMode().
API_GET_FSM_ID = 7001
API_GET_FSM_MODE = 7002

# G1 Arm Action Service (constants from the official unitree_sdk2_python
# g1/arm/g1_arm_action_api.py - the installed SDK is too old to have it).
ARM_ACTION_SERVICE_NAME = "arm"
ARM_ACTION_API_VERSION = "1.0.0.14"
API_ARM_EXECUTE_ACTION = 7106
API_ARM_GET_ACTION_LIST = 7107
ARM_RELEASE = 99  # return arms to the initial pose


class MotionBackend(Protocol):
    """
    Minimal non-blocking motion interface used by the teleop controller.

    set_velocity() must return immediately. The robot keeps moving only
    for `duration` seconds, so if the caller dies the robot stops by itself.
    """

    def set_velocity(
        self, vx: float, vy: float, yaw: float, duration: float
    ) -> None: ...

    def stop(self) -> None: ...

    def get_fsm_id(self) -> int | None: ...

    def get_fsm_mode(self) -> int | None: ...

    def damp(self) -> None: ...

    def set_fsm(self, fsm_id: int) -> None: ...

    def execute_arm_action(self, action_id: int) -> int: ...


@dataclass
class MockMotionBackend:
    """Records commands instead of moving a robot. Used in tests and --mock."""

    fsm_id: int | None = 500
    fsm_mode: int | None = 0
    verbose: bool = False
    commands: list[tuple[float, float, float, float]] = field(
        default_factory=list
    )
    fsm_requests: list[int] = field(default_factory=list)
    stop_count: int = 0
    fail_next: bool = False
    arm_actions: list[int] = field(default_factory=list)
    arm_codes: list[int] = field(default_factory=list)  # queued return codes

    def set_velocity(
        self, vx: float, vy: float, yaw: float, duration: float
    ) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("mock RPC failure")
        self.commands.append((vx, vy, yaw, duration))
        if self.verbose:
            print(
                f"[MOCK] SetVelocity vx={vx:+.2f} vy={vy:+.2f} "
                f"yaw={yaw:+.2f} dur={duration:.2f}"
            )

    def stop(self) -> None:
        self.stop_count += 1
        if self.verbose:
            print("[MOCK] StopMove")

    def get_fsm_id(self) -> int | None:
        return self.fsm_id

    def get_fsm_mode(self) -> int | None:
        return self.fsm_mode

    def damp(self) -> None:
        self.set_fsm(FSM_DAMP)

    def set_fsm(self, fsm_id: int) -> None:
        self.fsm_requests.append(fsm_id)
        self.fsm_id = fsm_id
        if self.verbose:
            print(f"[MOCK] SetFsmId({fsm_id})")

    def execute_arm_action(self, action_id: int) -> int:
        self.arm_actions.append(action_id)
        if self.verbose:
            print(f"[MOCK] ArmAction ExecuteAction({action_id})")
        return self.arm_codes.pop(0) if self.arm_codes else 0


class UnitreeMotionBackend:
    """
    Real G1 backend using unitree_sdk2py LocoClient.

    * Motion: SetVelocity(vx, vy, omega, duration) - returns immediately.
    * FSM read: GetFsmId() if the SDK has it, otherwise the raw RPC
      api 7001 (same method as SafetyController). The installed SDK in
      g1pilot-dev has no GetFsmId().
    * Service name: the container's SDK is patched to "sport" (Day 01).
      Pass service_name to force it without relying on that patch.
    """

    def __init__(
        self,
        interface: str = "enP2p1s0",
        service_name: str | None = "sport",
    ) -> None:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        import unitree_sdk2py.g1.loco.g1_loco_client as loco_module

        if service_name:
            loco_module.LOCO_SERVICE_NAME = service_name

        ChannelFactoryInitialize(0, interface)

        self._client = loco_module.LocoClient()
        # Short timeout: a teleop loop must never hang for seconds on RPC.
        self._client.SetTimeout(1.0)
        self._client.Init()
        self._lock = threading.Lock()
        self.service_name = loco_module.LOCO_SERVICE_NAME
        print(f"[teleop] Unitree service name: {self.service_name}")

        # Arm gestures use their own client and lock: ExecuteAction blocks
        # for several seconds and must never delay a locomotion stop.
        self._arm = _make_arm_client()
        self._arm_lock = threading.Lock()

    def set_velocity(
        self, vx: float, vy: float, yaw: float, duration: float
    ) -> None:
        with self._lock:
            code = self._client.SetVelocity(
                float(vx), float(vy), float(yaw), float(duration)
            )
        if code not in (0, None):
            raise RuntimeError(f"SetVelocity failed with code {code}")

    def stop(self) -> None:
        with self._lock:
            if hasattr(self._client, "StopMove"):
                self._client.StopMove()
            else:
                self._client.SetVelocity(0.0, 0.0, 0.0, 1.0)

    def _read_int(self, api_id: int) -> int | None:
        try:
            with self._lock:
                code, data = self._client._Call(api_id, "")
            if code != 0 or not data:
                return None
            value = json.loads(data).get("data")
            return None if value is None else int(value)
        except Exception as exc:
            print(f"[teleop] FSM read (api {api_id}) failed: {exc}")
            return None

    def get_fsm_id(self) -> int | None:
        if hasattr(self._client, "GetFsmId"):
            try:
                with self._lock:
                    code, fsm_id = self._client.GetFsmId()
                if code == 0 and fsm_id is not None:
                    return int(fsm_id)
            except Exception:
                pass
        return self._read_int(API_GET_FSM_ID)

    def get_fsm_mode(self) -> int | None:
        return self._read_int(API_GET_FSM_MODE)

    def damp(self) -> None:
        with self._lock:
            code = self._client.Damp()
        if code not in (0, None):
            raise RuntimeError(f"Damp failed with code {code}")

    def set_fsm(self, fsm_id: int) -> None:
        with self._lock:
            code = self._client.SetFsmId(int(fsm_id))
        if code not in (0, None):
            raise RuntimeError(f"SetFsmId({fsm_id}) failed with code {code}")


    def execute_arm_action(self, action_id: int) -> int:
        """Blocking until the gesture finishes. Returns the RPC code."""
        payload = json.dumps({"data": int(action_id)})
        with self._arm_lock:
            code, _data = self._arm._Call(API_ARM_EXECUTE_ACTION, payload)
        return int(code)

    def get_arm_action_list(self):
        with self._arm_lock:
            code, data = self._arm._Call(API_ARM_GET_ACTION_LIST, "{}")
        return code, (json.loads(data) if code == 0 and data else None)


def _make_arm_client():
    """G1ArmActionClient rebuilt on the SDK's generic RPC Client."""
    from unitree_sdk2py.rpc.client import Client

    class _ArmActionClient(Client):
        def __init__(self):
            super().__init__(ARM_ACTION_SERVICE_NAME, False)

        def Init(self):
            self._SetApiVerson(ARM_ACTION_API_VERSION)
            self._RegistApi(API_ARM_EXECUTE_ACTION, 0)
            self._RegistApi(API_ARM_GET_ACTION_LIST, 0)

    client = _ArmActionClient()
    client.SetTimeout(20.0)  # gestures take several seconds
    client.Init()
    return client
