"""Attract mode API (Studio -> Visitor App page)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import attract_service
from app.services.system_control import system_control

router = APIRouter(prefix="/api/attract", tags=["Attract mode"])


class SettingsBody(BaseModel):
    pin: str = ""
    enabled: bool | None = None
    wave: bool | None = None
    cooldown_s: int | None = None
    min_box_height: float | None = None
    text_en: str | None = None
    text_de: str | None = None
    languages: list[str] | None = None


class PinBody(BaseModel):
    pin: str = ""


def _pin(pin):
    try:
        system_control.check_pin(pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@router.get("")
async def get_status():
    return attract_service.status()


@router.put("")
async def put_settings(body: SettingsBody):
    _pin(body.pin)
    attract_service.save(body.model_dump(exclude={"pin"}, exclude_none=True))
    return attract_service.status()


@router.post("/greet")
async def greet_now(body: PinBody):
    """Test the greeting once (ignores camera and cooldown, but not the robot rules)."""
    _pin(body.pin)
    await run_in_threadpool(attract_service.greet, attract_service.load())
    return attract_service.status()
