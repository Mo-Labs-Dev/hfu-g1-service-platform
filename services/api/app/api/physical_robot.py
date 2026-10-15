from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/physical-robot",
    tags=["Physical Robot"],
)

BRIDGE_BASE_URL = "http://127.0.0.1:8767"

# Physical posture control: Damp and Stand Up.
POSTURE_CONTROL_ENABLED = (
    os.getenv("G1_ALLOW_POSTURE_COMMANDS") == "1"
)

# Separate authorization for entering FSM 500.
LOCOMOTION_CONTROL_ENABLED = (
    os.getenv("G1_ALLOW_LOCOMOTION_COMMANDS") == "1"
)

BRIDGE_TOKEN = os.getenv("G1_BRIDGE_TOKEN", "")

POSTURE_ACTIONS = ("damp", "stand_up")
LOCOMOTION_ACTION = "start_locomotion"


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


async def fetch_bridge_status() -> dict:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(5.0)
    ) as client:
        response = await client.get(
            f"{BRIDGE_BASE_URL}/status"
        )
        response.raise_for_status()
        return response.json()


async def fetch_bridge_health() -> dict:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(3.0)
    ) as client:
        response = await client.get(
            f"{BRIDGE_BASE_URL}/health"
        )
        response.raise_for_status()
        return response.json()


@router.get(
    "/status",
    response_model=PhysicalRobotStatus,
)
async def get_physical_robot_status():
    try:
        data = await fetch_bridge_status()

        return PhysicalRobotStatus(
            connected=data.get("connected") is True,
            source="physical_g1",
            fsm_id=data.get("fsm_id"),
            locomotion_mode=data.get(
                "locomotion_mode", False
            ),
            motion_enabled=False,
            timestamp=data.get("timestamp"),
            error=data.get("error"),
        )

    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
    ) as error:
        logger.warning(
            "Physical G1 status unavailable: %s",
            error,
        )

        return PhysicalRobotStatus(
            connected=False,
            error="Physical G1 status bridge unavailable",
        )


@router.get(
    "/control-capabilities",
    response_model=ControlCapabilities,
)
async def get_control_capabilities():
    try:
        health = await fetch_bridge_health()
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
    ):
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

    if posture_available and locomotion_available:
        message = (
            "Posture and locomotion FSM requests are armed. "
            "Operator supervision and physical safety checks "
            "are required."
        )
    elif posture_available:
        message = (
            "Posture requests are armed. "
            "Locomotion FSM control remains locked."
        )
    elif locomotion_available:
        message = (
            "Locomotion FSM control is armed. "
            "Posture control remains locked."
        )
    else:
        message = "Physical robot control is locked."

    return ControlCapabilities(
        posture_control_available=posture_available,
        locomotion_control_available=locomotion_available,
        physical_motion_enabled=False,
        message=message,
    )


@router.post(
    "/posture",
    response_model=PostureResult,
)
async def request_posture(
    request: PostureRequest,
):
    is_locomotion = (
        request.action == LOCOMOTION_ACTION
    )

    if is_locomotion:
        action_enabled = LOCOMOTION_CONTROL_ENABLED
    else:
        action_enabled = POSTURE_CONTROL_ENABLED

    if not action_enabled or not BRIDGE_TOKEN:
        raise HTTPException(
            status_code=403,
            detail=(
                "Requested physical robot control "
                "is not armed"
            ),
        )

    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Operator confirmation is required",
        )

    try:
        # The bridge independently checks:
        # - Authorization token
        # - Source FSM
        # - Exclusive SDK request lock
        # - Target FSM response
        #
        # No velocity or walking commands are sent here.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0)
        ) as client:
            response = await client.post(
                f"{BRIDGE_BASE_URL}/posture",
                json={
                    "action": request.action,
                    "confirmed": True,
                },
                headers={
                    "X-G1-Bridge-Token": BRIDGE_TOKEN,
                },
            )

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Invalid bridge payload")

        if response.status_code != 200:
            logger.warning(
                "G1 control request %s returned HTTP %s",
                request.action,
                response.status_code,
            )

            raise HTTPException(
                status_code=response.status_code,
                detail=data.get(
                    "error",
                    "Physical G1 control request unsuccessful",
                ),
            )

        return PostureResult(
            status=data.get("status", "unverified"),
            action=data.get(
                "action",
                request.action,
            ),
            before_fsm=data.get("before_fsm"),
            after_fsm=data.get("after_fsm"),
            physical_posture_verified=False,
            physical_motion_verified=False,
        )

    except httpx.HTTPError as error:
        logger.exception(
            "G1 control bridge communication failed"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to communicate with the "
                "physical G1 control bridge"
            ),
        ) from error

    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=502,
            detail="Invalid response from G1 bridge",
        ) from error
