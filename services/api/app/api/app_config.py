"""Visitor-app configuration (Studio -> G1 Remote app, pushed live over /ws)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.websocket import manager
from app.services import app_config_service
from app.services.system_control import system_control

router = APIRouter(prefix="/api/app", tags=["Visitor app"])


class Announcement(BaseModel):
    active: bool | None = None
    level: str | None = None
    text_en: str | None = None
    text_de: str | None = None


class ConfigBody(BaseModel):
    pin: str = ""
    announcement: Announcement | None = None
    tiles: dict[str, bool] | None = None


@router.get("/config")
async def get_config():
    return {**app_config_service.load(), "tile_names": app_config_service.TILES}


@router.put("/config")
async def put_config(body: ConfigBody):
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    try:
        cfg = app_config_service.save(body.model_dump(exclude={"pin"}, exclude_none=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await manager.broadcast({"type": "app_config_changed", "data": {"version": cfg["version"]}})
    return {**cfg, "clients": len(manager.active_connections)}


@router.get("/battery")
async def battery():
    """Battery level for the apps (also pushed as {"type": "battery"} over /ws)."""
    from app.services.battery_watch import watch
    return watch.state()


@router.get("/clients")
async def clients():
    """How many apps / pages are connected to the live channel right now."""
    return {"connected": len(manager.active_connections)}


async def notify_routes_changed(route: str) -> None:
    await manager.broadcast({"type": "routes_changed", "data": {"route": route}})
