from __future__ import annotations

import logging
from datetime import datetime

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/physical-robot",
    tags=["Physical Robot"],
)

BRIDGE_URL = "http://127.0.0.1:8767/status"


class PhysicalRobotStatus(BaseModel):
    connected: bool
    source: str = "physical_g1"
    fsm_id: int | None = None
    locomotion_mode: bool = False
    motion_enabled: bool = False
    timestamp: datetime | None = None
    error: str | None = None


@router.get("/status", response_model=PhysicalRobotStatus)
async def get_physical_robot_status():
    try:
        timeout = httpx.Timeout(5.0)

        async with httpx.AsyncClient(
            timeout=timeout
        ) as client:
            response = await client.get(BRIDGE_URL)
            response.raise_for_status()
            data = response.json()

        return PhysicalRobotStatus(
            connected=data.get("connected") is True,
            source="physical_g1",
            fsm_id=data.get("fsm_id"),
            locomotion_mode=data.get(
                "locomotion_mode", False
            ),
            motion_enabled=False,
            timestamp=data.get("timestamp"),
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