"""Point-at-it live demonstration (robot service on port 8005) - proxy for the app and Studio."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import robot_hub
from app.services.robot_hub import HubError

router = APIRouter(prefix="/api/pick", tags=["Live demonstration"])
LOG = os.path.expanduser(os.getenv("G1_PICK_LOG", "~/Documents/Projekte/g1pilot-main/hfu_pick/logs/point_runs.jsonl"))


class PointBody(BaseModel):
    target: str
    lang: str = "en"


async def _call(fn, *a):
    try:
        return await run_in_threadpool(fn, *a)
    except HubError as exc:
        raise HTTPException(503, f"Point-at-it demo not running ({exc})")


@router.get("/status")
async def status():
    return await _call(robot_hub.pick_status)


@router.get("/scene")
async def scene():
    return await _call(robot_hub.pick_scene)


@router.get("/view.jpg")
async def view():
    data, ctype = await _call(robot_hub.pick_view)
    return Response(content=data, media_type=ctype or "image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/point")
async def point(body: PointBody):
    code, data = await _call(robot_hub.pick_point, body.target, body.lang)
    if code >= 400:
        raise HTTPException(409 if code == 409 else 502, (data or {}).get("detail", "could not start"))
    return data


@router.post("/stop")
async def stop():
    code, data = await _call(robot_hub.pick_stop)
    return data


@router.get("/runs")
async def runs():
    """Run log of the demo (for Evaluation): newest first."""
    out = []
    try:
        with open(LOG) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    done = [r for r in out if r.get("result") == "done"]
    return {"runs": out[::-1][:200], "total": len(out), "done": len(done),
            "success_rate": round(len(done) / len(out), 3) if out else None}
