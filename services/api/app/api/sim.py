"""Simulation + path planner API (no robot motion - no PIN needed)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.services import sim_service

router = APIRouter(prefix="/api/sim", tags=["Simulation"])


class Person(BaseModel):
    x: float
    y: float
    t_from: float = 0.0
    t_to: float = 1e9


class RunBody(BaseModel):
    route: str
    lang: str = "en"
    return_home: bool = True
    people: list[Person] = Field(default_factory=list)


class PlanBody(BaseModel):
    start: list[float]
    goal: list[float]


class PathRunBody(BaseModel):
    path: list[list[float]]
    lang: str = "en"
    people: list[Person] = Field(default_factory=list)


def _people(items):
    return [p.model_dump() for p in items][:30]


@router.post("/run")
async def run(body: RunBody):
    try:
        route, source = await run_in_threadpool(sim_service.route_in_map, body.route)
    except KeyError:
        raise HTTPException(404, f"Unknown route '{body.route}'")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    res = await run_in_threadpool(sim_service.simulate, route, body.lang, _people(body.people), body.return_home)
    return {**res, "route": body.route, "map_source": source}


@router.post("/plan")
async def plan(body: PlanBody):
    if len(body.start) != 2 or len(body.goal) != 2:
        raise HTTPException(400, "start and goal must be [x, y]")
    try:
        return await run_in_threadpool(sim_service.planner().plan, tuple(body.start), tuple(body.goal))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/run_path")
async def run_path(body: PathRunBody):
    if len(body.path) < 2:
        raise HTTPException(400, "Path needs at least 2 points")
    route = sim_service.route_from_path(body.path)
    res = await run_in_threadpool(sim_service.simulate, route, body.lang, _people(body.people), False)
    return {**res, "route": "planned_path"}
