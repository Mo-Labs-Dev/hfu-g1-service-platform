from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/physical-robot",
    tags=["Physical Robot"],
)

BRIDGE_BASE_URL = os.getenv(
    "G1_BRIDGE_URL",
    "http://127.0.0.1:8767",
).rstrip("/")

MOTION_SIMULATOR_URL = os.getenv(
    "G1_MOTION_SIMULATOR_URL",
    "http://127.0.0.1:8768",
).rstrip("/")

BRIDGE_TOKEN = os.getenv("G1_BRIDGE_TOKEN", "")

POSTURE_CONTROL_ENABLED = (
    os.getenv("G1_ALLOW_POSTURE_COMMANDS") == "1"
)

LOCOMOTION_CONTROL_ENABLED = (
    os.getenv("G1_ALLOW_LOCOMOTION_COMMANDS") == "1"
)


class PhysicalRobotStatus(BaseModel):
    connected: bool
    source: str = "physical_g1"
    fsm_id: int | None = None
    locomotion_mode: bool = False
    motion_enabled: bool = False
    timestamp: datetime | None = None
    error: str | None = None


class ControlCapabilities(BaseModel):
    posture_control_available: bool = False
    locomotion_control_available: bool = False
    supported_actions: list[str] = Field(
        default_factory=lambda: [
            "damp",
            "stand_up",
            "start_locomotion",
        ]
    )
    required_sequence: list[int] = Field(
        default_factory=lambda: [0, 1, 4, 500]
    )
    physical_motion_enabled: bool = False
    message: str


class PostureRequest(BaseModel):
    action: Literal[
        "damp",
        "stand_up",
        "start_locomotion",
    ]
    confirmed: bool = False


class PostureResult(BaseModel):
    status: str
    action: str | None = None
    before_fsm: int | None = None
    after_fsm: int | None = None
    physical_posture_verified: bool = False
    physical_motion_verified: bool = False
    error: str | None = None


class MotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vx: float = Field(ge=-0.10, le=0.10)
    vy: float = Field(ge=-0.10, le=0.10)
    omega: float = Field(ge=-0.15, le=0.15)


class MotionStatus(BaseModel):
    mode: Literal["simulation"] = "simulation"
    physical_motion_enabled: Literal[False] = False
    fsm_id: int = 500
    velocity: list[float]
    moving: bool


class MotionResult(BaseModel):
    status: str
    velocity: list[float]
    physical_motion_enabled: Literal[False] = False


async def bridge_request(
    method: str,
    path: str,
    payload: dict | None = None,
    timeout: float = 5.0,
) -> dict:
    headers = {}

    if method == "POST":
        if not BRIDGE_TOKEN:
            raise HTTPException(
                status_code=403,
                detail="G1 bridge control token not configured",
            )
        headers["X-G1-Bridge-Token"] = BRIDGE_TOKEN

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                f"{BRIDGE_BASE_URL}{path}",
                json=payload,
                headers=headers,
            )

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Invalid bridge response")

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=data.get("error", "Bridge request failed"),
            )

        return data

    except httpx.HTTPError as error:
        logger.warning("Bridge communication failed: %s", error)
        raise HTTPException(
            status_code=503,
            detail="Physical G1 bridge unavailable",
        ) from error

    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=502,
            detail="Invalid physical G1 bridge response",
        ) from error


@router.get("/status", response_model=PhysicalRobotStatus)
async def get_physical_robot_status():
    try:
        data = await bridge_request("GET", "/status")
        return PhysicalRobotStatus(
            connected=data.get("connected") is True,
            source="physical_g1",
            fsm_id=data.get("fsm_id"),
            locomotion_mode=data.get("locomotion_mode", False),
            motion_enabled=False,
            timestamp=data.get("timestamp"),
            error=data.get("error"),
        )
    except HTTPException:
        return PhysicalRobotStatus(
            connected=False,
            error="Physical G1 bridge unavailable",
        )


@router.get(
    "/control-capabilities",
    response_model=ControlCapabilities,
)
async def get_control_capabilities():
    try:
        health = await bridge_request("GET", "/health")
    except HTTPException:
        health = {}

    posture_available = (
        POSTURE_CONTROL_ENABLED
        and bool(BRIDGE_TOKEN)
        and health.get("posture_control_available") is True
    )

    locomotion_available = (
        LOCOMOTION_CONTROL_ENABLED
        and bool(BRIDGE_TOKEN)
        and health.get("locomotion_control_available") is True
    )

    return ControlCapabilities(
        posture_control_available=posture_available,
        locomotion_control_available=locomotion_available,
        physical_motion_enabled=False,
        message=(
            "FSM controls available; physical walking "
            "requires separate safety authorization."
            if posture_available or locomotion_available
            else "Physical robot control is locked."
        ),
    )


@router.post("/posture", response_model=PostureResult)
async def request_posture(request: PostureRequest):
    enabled = (
        LOCOMOTION_CONTROL_ENABLED
        if request.action == "start_locomotion"
        else POSTURE_CONTROL_ENABLED
    )

    if not enabled:
        raise HTTPException(
            status_code=403,
            detail="Requested FSM control is disabled",
        )

    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Operator confirmation required",
        )

    data = await bridge_request(
        "POST",
        "/posture",
        {
            "action": request.action,
            "confirmed": True,
        },
        timeout=15.0,
    )

    return PostureResult(
        status=data.get("status", "unverified"),
        action=data.get("action", request.action),
        before_fsm=data.get("before_fsm"),
        after_fsm=data.get("after_fsm"),
        physical_posture_verified=False,
        physical_motion_verified=False,
    )


@router.get("/motion/status", response_model=MotionStatus)
async def get_motion_status():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{MOTION_SIMULATOR_URL}/motion/status"
            )
            response.raise_for_status()

        data = response.json()

        if (
            data.get("mode") != "simulation"
            or data.get("physical_motion_enabled") is not False
        ):
            raise ValueError("Simulator identity mismatch")

        return MotionStatus.model_validate(data)

    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise HTTPException(
            status_code=503,
            detail="Motion simulator unavailable",
        ) from error


@router.post("/motion", response_model=MotionResult)
async def request_simulated_motion(request: MotionRequest):
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                f"{MOTION_SIMULATOR_URL}/motion",
                json=request.model_dump(),
            )
            response.raise_for_status()

        data = response.json()

        if (
            data.get("status") != "simulated"
            or data.get("physical_motion_enabled") is not False
        ):
            raise ValueError("Unexpected simulator response")

        return MotionResult.model_validate(data)

    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise HTTPException(
            status_code=503,
            detail="Simulated motion failed",
        ) from error


@router.post("/motion/stop")
async def stop_simulated_motion():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                f"{MOTION_SIMULATOR_URL}/motion/stop"
            )
            response.raise_for_status()

        data = response.json()

        if data.get("status") != "stopped":
            raise ValueError("Unexpected simulator response")

        return {
            "status": "stopped",
            "mode": "simulation",
            "physical_motion_enabled": False,
        }

    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise HTTPException(
            status_code=503,
            detail="Simulated stop failed",
        ) from error


@router.get("/physical-motion/status")
async def get_physical_motion_status():
    data = await bridge_request(
        "GET",
        "/physical-motion/status",
    )

    if data.get("source") != "physical_g1":
        raise HTTPException(
            status_code=502,
            detail="Unexpected physical bridge identity",
        )

    return data


@router.post("/physical-motion/stop")
async def request_physical_stop():
    """
    Forward an authenticated zero-velocity stop request.

    A successful SDK response does NOT prove physical stopping.
    """
    data = await bridge_request(
        "POST",
        "/physical-motion/stop",
        timeout=5.0,
    )

    data["stop_verified"] = False
    return data


@router.post("/physical-motion/disarm")
async def request_physical_disarm():
    data = await bridge_request(
        "POST",
        "/physical-motion/disarm",
        timeout=5.0,
    )

    data["stop_verified"] = False
    return data


@router.post("/physical-motion/arm")
async def reject_physical_motion_arm():
    raise HTTPException(
        status_code=403,
        detail="Physical motion arming is not enabled through FastAPI",
    )


@router.post("/physical-motion")
async def reject_physical_motion():
    raise HTTPException(
        status_code=403,
        detail="Continuous physical velocity commands are disabled",
    )
