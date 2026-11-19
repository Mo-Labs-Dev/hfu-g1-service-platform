"""Mission Control API: live overview, STOP/E-stop, tours, camera, service control."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import robot_hub
from app.services.robot_hub import HubError
from app.services.system_control import system_control

router = APIRouter(prefix="/api/mission", tags=["Mission Control"])


class PinBody(BaseModel):
    pin: str = ""


class ActionBody(PinBody):
    home_confirmed: bool = False


class GuideStartBody(PinBody):
    route: str
    lang: str = "en"


@router.get("/overview")
async def overview():
    return await run_in_threadpool(robot_hub.overview)


# STOP / E-stop need no PIN: anyone may stop the robot.
@router.post("/stop")
async def stop():
    try:
        return await run_in_threadpool(robot_hub.stop)
    except HubError as exc:
        raise HTTPException(503, f"Teleop server not reachable: {exc}")


@router.post("/estop")
async def estop():
    try:
        return await run_in_threadpool(robot_hub.estop)
    except HubError as exc:
        raise HTTPException(503, f"Teleop server not reachable: {exc}")


@router.post("/pin/check")
async def pin_check(body: PinBody):
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"ok": True}


# ------------------------------------------------------------- tours / guide
@router.get("/routes")
async def routes():
    try:
        return await run_in_threadpool(robot_hub.routes)
    except HubError as exc:
        raise HTTPException(503, f"Guide mode is not running ({exc}).")


@router.post("/guide/start")
async def guide_start(body: GuideStartBody):
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    try:
        code, res = await run_in_threadpool(robot_hub.guide_start, body.route, body.lang)
    except HubError as exc:
        raise HTTPException(503, f"Guide mode is not running ({exc}).")
    if code >= 400:
        raise HTTPException(409, (res or {}).get("detail", "Guide refused to start"))
    return res


@router.post("/guide/cancel")
async def guide_cancel():
    try:
        code, res = await run_in_threadpool(robot_hub.guide_cancel)
    except HubError as exc:
        raise HTTPException(503, str(exc))
    return res


# ------------------------------------------------------------- camera
@router.get("/camera/snapshot")
async def camera_snapshot():
    try:
        data, ctype = await run_in_threadpool(robot_hub.camera_snapshot)
    except HubError as exc:
        raise HTTPException(503, f"Camera not available ({exc})")
    return Response(content=data, media_type=ctype or "image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.get("/camera/detect")
async def camera_detect():
    """Snapshot + YOLO boxes (for the overlay in Mission Control)."""
    try:
        data, _ = await run_in_threadpool(robot_hub.camera_snapshot)
    except HubError as exc:
        raise HTTPException(503, f"Camera not available ({exc})")
    from app.services.vision_service import vision_service
    try:
        result = await run_in_threadpool(vision_service.detect, data, 0.35)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result


# ------------------------------------------------------------- service control
@router.get("/actions")
async def actions():
    return {"actions": system_control.list(), **system_control.status()}


@router.get("/actions/status")
async def actions_status():
    return system_control.status()


@router.post("/actions/{action}")
async def run_action(action: str, body: ActionBody):
    try:
        return system_control.start(action, body.pin, body.home_confirmed)
    except KeyError:
        raise HTTPException(404, f"Unknown action '{action}'")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
