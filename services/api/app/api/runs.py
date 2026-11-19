"""Evaluation API: guide / tour run log, statistics, CSV export."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import runs_service
from app.services.system_control import system_control

router = APIRouter(prefix="/api/runs", tags=["Evaluation"])


class MetaBody(BaseModel):
    pin: str = ""
    note: str | None = None
    excluded: bool | None = None


def _filtered(route: str | None, since: str | None):
    runs = runs_service.load_runs()
    if route:
        runs = [r for r in runs if r.get("route") == route]
    if since:
        runs = [r for r in runs if r.get("started", "") >= since]
    return runs


@router.get("")
async def list_runs(route: str | None = None, since: str | None = None):
    runs = await run_in_threadpool(lambda: runs_service.with_map_positions(_filtered(route, since)))
    return {"runs": list(reversed(runs)), "stats": runs_service.stats(runs),
            "routes": sorted({r.get("route", "") for r in runs_service.load_runs()})}


@router.get("/export.csv")
async def export_csv(route: str | None = None, since: str | None = None):
    text = runs_service.to_csv(_filtered(route, since))
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="g1_guide_runs.csv"'})


@router.put("/{run_id}")
async def edit_run(run_id: str, body: MetaBody):
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return runs_service.set_meta(run_id, body.note, body.excluded)
