"""Studio extras: visitor insights + knowledge editor, Show mode, live activity / replay, evaluation summary."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.services import activity_service, evaluation_service, insights_service, show_service
from app.services.system_control import system_control

router = APIRouter(tags=["Studio extras"])


def _pin(pin: str) -> None:
    try:
        system_control.check_pin(pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


class PinBody(BaseModel):
    pin: str = ""


# ---------------------------------------------------------------- insights + knowledge
@router.get("/api/insights/questions")
async def insights_questions(days: int = 30):
    return await run_in_threadpool(insights_service.questions, max(1, min(days, 365)))


@router.get("/api/knowledge")
async def knowledge_list():
    return {"entries": insights_service.load_knowledge()}


class KnowledgeBody(BaseModel):
    pin: str = ""
    entries: list[dict]


@router.put("/api/knowledge")
async def knowledge_save(body: KnowledgeBody):
    _pin(body.pin)
    try:
        return {"entries": insights_service.save_knowledge(body.entries)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MatchBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@router.post("/api/knowledge/match")
async def knowledge_match(body: MatchBody):
    return {"matches": insights_service.match(body.question)}


# ---------------------------------------------------------------- show mode
def _runner():
    if show_service.runner is None:
        raise HTTPException(503, "Show runner not started (backend starting up?)")
    return show_service.runner


@router.get("/api/shows")
async def shows_list():
    from app.services import destinations_service
    try:
        dests = [{"name": d["name"], "title": d.get("title_en") or d["name"]} for d in destinations_service.list_all()]
    except Exception:
        dests = []
    return {"shows": show_service.load_shows(), "state": show_service.runner.snapshot() if show_service.runner else None,
            "destinations": dests, "gestures": list(show_service.GESTURES), "targets": list(show_service.TARGETS),
            "max_steps": show_service.MAX_STEPS}


class ShowBody(BaseModel):
    pin: str = ""
    show: dict


@router.put("/api/shows")
async def shows_save(body: ShowBody):
    _pin(body.pin)
    try:
        return show_service.save_show(body.show)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/shows/{show_id}/delete")
async def shows_delete(show_id: str, body: PinBody):
    _pin(body.pin)
    try:
        show_service.delete_show(show_id)
    except KeyError:
        raise HTTPException(404, "Unknown show")
    return {"deleted": show_id}


class StartBody(BaseModel):
    pin: str = ""
    mode: Literal["auto", "step"] = "step"
    lang: Literal["en", "de"] | None = None
    start_at: int = 0


@router.post("/api/shows/{show_id}/start")
async def shows_start(show_id: str, body: StartBody):
    _pin(body.pin)
    try:
        show = show_service.get_show(show_id)
    except KeyError:
        raise HTTPException(404, "Unknown show")
    try:
        return _runner().start(show, body.mode, body.lang, body.start_at)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc))


@router.post("/api/shows/stop")
async def shows_stop():
    """No PIN on purpose: stopping must always be possible."""
    return await run_in_threadpool(_runner().stop)


@router.post("/api/shows/next")
async def shows_next(body: PinBody):
    _pin(body.pin)
    try:
        return _runner().next()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.get("/api/shows/state")
async def shows_state():
    return _runner().snapshot()


@router.get("/api/shows/runs")
async def shows_runs(limit: int = 50):
    return {"runs": list(reversed(show_service.load_runs()))[:max(1, min(limit, 500))]}


# ---------------------------------------------------------------- live activity + replay
@router.get("/api/activity")
async def activity(limit: int = 80):
    return {"events": activity_service.recent(max(1, min(limit, 200))), **activity_service.tracker.snapshot()}


@router.get("/api/activity/paths")
async def activity_paths():
    return {"paths": await run_in_threadpool(activity_service.list_trajectories)}


@router.get("/api/activity/paths/{path_id}")
async def activity_path(path_id: str):
    try:
        return await run_in_threadpool(activity_service.get_trajectory, path_id)
    except (KeyError, OSError, ValueError):
        raise HTTPException(404, "Unknown recording")


# ---------------------------------------------------------------- evaluation summary
@router.get("/api/evaluation/summary")
async def evaluation_summary(days: int = 0):
    return await run_in_threadpool(evaluation_service.summary, max(0, min(days, 365)))


@router.get("/api/evaluation/export/{kind}.csv")
async def evaluation_export(kind: str):
    try:
        text = await run_in_threadpool(evaluation_service.export, kind)
    except KeyError:
        raise HTTPException(404, "kind must be conversations, points, shows or paths")
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="g1_{kind}.csv"'})
