"""Lab map API: Session 03 map, routes/tours/stops in map frame, HOME, live G1 pose."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import content_service, robot_hub
from app.services.lab_map_service import lab_map
from app.services.robot_hub import HubError
from app.services.system_control import system_control

router = APIRouter(prefix="/api/map", tags=["Lab Map"])


class HomeBody(BaseModel):
    pin: str = ""
    x: float
    y: float
    yaw: float


class PinBody(BaseModel):
    pin: str = ""


def _pin(pin: str):
    try:
        system_control.check_pin(pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@router.get("/info")
async def info():
    try:
        return {**(await run_in_threadpool(lab_map.info)), "alignment": lab_map.alignment()}
    except OSError as exc:
        raise HTTPException(503, f"Map files missing: {exc}")


@router.get("/image.png")
async def image():
    try:
        png = await run_in_threadpool(lab_map.png)
    except OSError as exc:
        raise HTTPException(503, f"Map files missing: {exc}")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/routes")
async def routes():
    return await run_in_threadpool(lab_map.routes)


@router.post("/home")
async def set_home(body: HomeBody):
    _pin(body.pin)
    return lab_map.set_home(body.x, body.y, body.yaw)


@router.post("/align/{route}")
async def align(route: str, body: PinBody):
    _pin(body.pin)
    try:
        return await run_in_threadpool(lab_map.align_route, route)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/live")
async def live():
    try:
        gp = await run_in_threadpool(robot_hub.guide_pose)
    except HubError:
        return {"pose": None, "detail": "Guide mode not running"}
    return {"pose": lab_map.live_pose(gp), "raw": gp}


# ------------------------------------------------------------------ tour editor
class RouteEdit(BaseModel):
    pin: str = ""
    title_en: str | None = None
    title_de: str | None = None
    intro_en: str | None = None
    intro_de: str | None = None


class StopEdit(BaseModel):
    pin: str = ""
    title_en: str | None = None
    title_de: str | None = None
    text_en: str | None = None
    text_de: str | None = None


class TranslateBody(BaseModel):
    text: str
    source: str = "en"
    target: str = "de"


class SayBody(PinBody):
    text: str
    lang: str = "en"


def _edit_errors(fn):
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(404, f"Not found: {exc}")
    except PermissionError as exc:
        raise HTTPException(500, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.put("/routes/{route}")
async def edit_route(route: str, body: RouteEdit):
    _pin(body.pin)
    return _edit_errors(lambda: lab_map.update_route(route, body.model_dump(exclude={"pin"})))


@router.put("/routes/{route}/stops/{stop}")
async def edit_stop(route: str, stop: str, body: StopEdit):
    _pin(body.pin)
    return _edit_errors(lambda: lab_map.update_stop(route, stop, body.model_dump(exclude={"pin"})))


@router.delete("/routes/{route}/stops/{stop}")
async def delete_stop(route: str, stop: str, pin: str = ""):
    _pin(pin)
    return _edit_errors(lambda: lab_map.delete_stop(route, stop))


@router.post("/translate")
async def translate(body: TranslateBody):
    try:
        text = await run_in_threadpool(content_service.translate, body.text, body.source, body.target)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(503, f"Local AI not available: {exc}")
    return {"text": text}


@router.post("/say")
async def say(body: SayBody):
    _pin(body.pin)
    try:
        return await run_in_threadpool(content_service.say_on_g1, body.text, body.lang)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(503, f"Voice bridge not available: {exc}")
