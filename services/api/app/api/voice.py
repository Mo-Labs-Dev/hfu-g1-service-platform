"""'Hey G1' listener status / switch (G1's own microphone)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import voice_listener
from app.services.system_control import system_control

router = APIRouter(prefix="/api/voice", tags=["Voice"])


class EnableBody(BaseModel):
    pin: str = ""
    enabled: bool


@router.get("/status")
async def status():
    lst = voice_listener.get()
    if lst is None:
        return {"running": False, "detail": "switched off (G1_VOICE_LISTENER=0)"}
    return {"running": True, **lst.state, "noise_floor_db": round(lst.seg.floor, 1)}


@router.post("/enable")
async def enable(body: EnableBody):
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    lst = voice_listener.get()
    if lst is None:
        raise HTTPException(409, "listener not running")
    lst.state["enabled"] = body.enabled
    return {"enabled": body.enabled}


class GestureBody(BaseModel):
    pin: str = ""
    enabled: bool


@router.get("/gestures")
async def gestures_status():
    from app.services import talk_gestures
    return {"enabled": talk_gestures.enabled()}


@router.post("/gestures")
async def gestures(body: GestureBody):
    """Arms gesture while G1 talks (off until tested on the robot)."""
    from app.services import talk_gestures
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    talk_gestures.set_enabled(body.enabled)
    return {"enabled": body.enabled}
