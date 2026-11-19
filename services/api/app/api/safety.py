"""Safety test API (Studio -> Safety tests page)."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import robot_hub, safety_test_service
from app.services.safety_test_service import safety_tests
from app.services.system_control import system_control

router = APIRouter(prefix="/api/safety", tags=["Safety tests"])


class TestBody(BaseModel):
    pin: str = ""
    kind: str
    note: str = ""


@router.post("/test")
async def start_test(body: TestBody):
    try:
        system_control.check_pin(body.pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    try:
        return await run_in_threadpool(safety_tests.start, body.kind, body.note)
    except KeyError:
        raise HTTPException(404, f"Unknown test '{body.kind}'")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.post("/cancel")
async def cancel():
    safety_tests.cancel()
    return safety_tests.status()


@router.get("/status")
async def status():
    try:
        tel = await run_in_threadpool(robot_hub.telemetry)
        motion = (tel or {}).get("motion")
    except Exception:
        motion = None
    return {**safety_tests.status(), "motion": motion}


@router.get("/results")
async def results():
    items = safety_test_service.load()
    return {"items": list(reversed(items)), "stats": safety_test_service.stats(items)}


@router.get("/export.csv")
async def export_csv():
    out = io.StringIO()
    fields = ["time", "kind", "label", "ok", "reaction_s", "stop_distance_m", "speed_at_trigger",
              "decel_mps2", "reason", "guide_message", "note"]
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in safety_test_service.load():
        w.writerow(r)
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="g1_safety_tests.csv"'})
