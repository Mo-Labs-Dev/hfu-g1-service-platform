"""Lab map API: Session 03 map, routes/tours/stops in map frame, HOME, live G1 pose."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import content_service, robot_hub
from app.services.lab_map_service import lab_map
from app.services.cloud3d_service import cloud3d
from app.services import destinations_service as dest
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


# ------------------------------------------------------------------ 3D LiDAR map
@router.get("/cloud3d.bin")
async def cloud3d_bin():
    try:
        blob, meta = await run_in_threadpool(cloud3d.blob)
    except OSError as exc:
        raise HTTPException(503, f"Map files missing: {exc}")
    return Response(content=blob, media_type="application/octet-stream",
                    headers={"X-Points": str(meta["points"]), "X-Source": meta["source"],
                             "Cache-Control": "no-cache"})


@router.get("/cloud3d/info")
async def cloud3d_info():
    try:
        return await run_in_threadpool(cloud3d.info)
    except OSError as exc:
        raise HTTPException(503, f"Map files missing: {exc}")


class BuildBody(BaseModel):
    pin: str = ""
    pcd: str | None = None
    voxel: float = 0.10


@router.post("/cloud3d/build")
async def cloud3d_build(body: BuildBody):
    _pin(body.pin)
    try:
        return await run_in_threadpool(cloud3d.build, body.pcd, max(0.05, min(body.voxel, 0.5)))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc))


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
    """G1 on the map. Best source: the map localizer (LiDAR matched to the map, works
    anywhere). Fallback: guide pose via HOME / route alignment."""
    gp = None
    try:
        gp = await run_in_threadpool(robot_hub.guide_pose)
    except HubError:
        pass
    try:
        lp = await run_in_threadpool(robot_hub.loc_pose)
    except HubError:
        lp = None
    return lab_map.combine_live(gp, lp)


class LocInit(BaseModel):
    pin: str = ""
    x: float | None = None
    y: float | None = None
    yaw: float | None = None
    home: bool = False


@router.get("/loc")
async def loc_status():
    try:
        return await run_in_threadpool(robot_hub.loc_status)
    except HubError as exc:
        raise HTTPException(503, f"Map localizer not running ({exc})")


@router.post("/loc/init")
async def loc_init(body: LocInit):
    _pin(body.pin)
    payload = {"home": True} if body.home else {"x": body.x, "y": body.y, "yaw": body.yaw}
    if not body.home and None in (body.x, body.y, body.yaw):
        raise HTTPException(400, "x, y and yaw are needed (or home: true)")
    try:
        code, data = await run_in_threadpool(robot_hub.loc_init, payload)
    except HubError as exc:
        raise HTTPException(503, f"Map localizer not running ({exc})")
    if code >= 400:
        raise HTTPException(code if code < 600 else 502, (data or {}).get("detail", "localizer error"))
    return data


@router.post("/loc/relocalize")
async def loc_relocalize(body: PinBody):
    _pin(body.pin)
    try:
        code, data = await run_in_threadpool(robot_hub.loc_relocalize)
    except HubError as exc:
        raise HTTPException(503, f"Map localizer not running ({exc})")
    if code >= 400:
        raise HTTPException(code if code < 600 else 502, (data or {}).get("detail", "localizer error"))
    return data


# ------------------------------------------------------------------ tour editor
class RouteEdit(BaseModel):
    pin: str = ""
    title_en: str | None = None
    title_de: str | None = None
    intro_en: str | None = None
    intro_de: str | None = None
    gesture_start: str | None = None
    gesture_end: str | None = None


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


async def _changed(route: str):
    from app.api.app_config import notify_routes_changed
    await notify_routes_changed(route)                 # tablets reload titles live


@router.put("/routes/{route}")
async def edit_route(route: str, body: RouteEdit):
    _pin(body.pin)
    res = _edit_errors(lambda: lab_map.update_route(route, body.model_dump(exclude={"pin"})))
    await _changed(route)
    return res


@router.put("/routes/{route}/stops/{stop}")
async def edit_stop(route: str, stop: str, body: StopEdit):
    _pin(body.pin)
    res = _edit_errors(lambda: lab_map.update_stop(route, stop, body.model_dump(exclude={"pin"})))
    await _changed(route)
    return res


@router.delete("/routes/{route}/stops/{stop}")
async def delete_stop(route: str, stop: str, pin: str = ""):
    _pin(pin)
    res = _edit_errors(lambda: lab_map.delete_stop(route, stop))
    await _changed(route)
    return res


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


# ------------------------------------------------------------------ autonomous walking
class DestinationBody(BaseModel):
    pin: str = ""
    name: str | None = None
    title_en: str = ""
    title_de: str = ""
    arrival_en: str = ""
    arrival_de: str = ""
    x: float
    y: float
    yaw: float | None = None


class GotoBody(BaseModel):
    pin: str = ""
    destination: str | None = None     # named destination (visitors, no PIN)
    x: float | None = None             # any point (operator, PIN)
    y: float | None = None
    yaw: float | None = None
    lang: str = "en"
    return_home: bool = False


class PlanBody(BaseModel):
    x: float
    y: float


@router.get("/destinations")
async def destinations():
    return dest.list_all()


@router.post("/destinations")
async def save_destination(body: DestinationBody):
    _pin(body.pin)
    item = _edit_errors(lambda: dest.upsert(body.model_dump(exclude={"pin"})))
    await _changed("destinations")
    return item


@router.delete("/destinations/{name}")
async def delete_destination(name: str, pin: str = ""):
    _pin(pin)
    _edit_errors(lambda: dest.delete(name))
    await _changed("destinations")
    return {"ok": True}


@router.get("/guide")
async def guide_status():
    """Running guide / autonomous walk (incl. the planned path) for the Lab Map."""
    try:
        return await run_in_threadpool(robot_hub.guide_status)
    except HubError:
        return {"state": "offline"}


@router.get("/nav")
async def nav_info():
    try:
        return await run_in_threadpool(robot_hub.guide_nav)
    except HubError as exc:
        return {"available": False, "reason": f"Guide mode not running ({exc})"}


@router.post("/plan")
async def plan(body: PlanBody):
    try:
        code, data = await run_in_threadpool(robot_hub.guide_plan, body.x, body.y)
    except HubError as exc:
        raise HTTPException(503, f"Guide mode not running ({exc})")
    if code >= 400:
        raise HTTPException(code if code < 600 else 502, (data or {}).get("detail", "planning failed"))
    return data


@router.post("/goto")
async def goto(body: GotoBody):
    if body.destination:
        try:
            d = dest.get(body.destination)
        except KeyError:
            raise HTTPException(404, f"Unknown destination '{body.destination}'")
        payload = {k: d.get(k) for k in ("x", "y", "yaw", "name", "title_en", "title_de", "arrival_en", "arrival_de")}
    else:
        _pin(body.pin)                     # any point on the map: operators only
        if body.x is None or body.y is None:
            raise HTTPException(400, "destination or x/y needed")
        payload = {"x": body.x, "y": body.y, "yaw": body.yaw, "name": "map_point",
                   "title_en": "this spot", "title_de": "diesem Punkt"}
    payload["lang"] = body.lang if body.lang in ("en", "de") else "en"
    home = lab_map.alignment().get("home")
    if body.return_home and home:
        payload.update({"return_home": True, "home": home})
    try:
        code, data = await run_in_threadpool(robot_hub.guide_goto, payload)
    except HubError as exc:
        raise HTTPException(503, f"Guide mode not running ({exc})")
    if code >= 400:
        raise HTTPException(409 if code == 409 else 502, (data or {}).get("detail", "could not start"))
    return data
