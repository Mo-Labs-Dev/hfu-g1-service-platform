"""Spoken tasks -> autonomous behaviour (see task_service)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.services import destinations_service, robot_hub
from app.services.lab_map_service import lab_map
from app.services.robot_hub import HubError
from app.services.task_service import TaskRunner, parse

router = APIRouter(prefix="/api/task", tags=["Tasks"])


def _point(target, lang):
    try:
        code, data = robot_hub.pick_point(target, lang)
    except HubError as exc:
        return False, str(exc)
    return code < 400, (data or {}).get("detail", "")


def _goto(name, lang):
    try:
        d = destinations_service.get(name)
    except KeyError:
        return False, f"unknown destination {name}"
    payload = {k: d.get(k) for k in ("x", "y", "yaw", "name", "title_en", "title_de")}
    payload["lang"] = lang
    try:
        code, data = robot_hub.guide_goto(payload)
    except HubError as exc:
        return False, str(exc)
    return code < 400, (data or {}).get("detail", "")


def _safe(fn):
    def call(*a):
        try:
            return fn(*a)
        except HubError:
            return {}
    return call


def _say(text, lang):
    try:
        robot_hub.post_json(f"{robot_hub.VOICE}/speak", {"text": text, "lang": lang, "queue": True}, timeout=3)
    except Exception:
        pass


runner = TaskRunner(scene=_safe(robot_hub.pick_scene), point=_point, pick_status=_safe(robot_hub.pick_status),
                    goto=_goto, guide_status=_safe(robot_hub.guide_status),
                    destinations=destinations_service.list_all, say=_say)


class TaskBody(BaseModel):
    text: str
    lang: str = "en"


@router.post("")
async def handle(body: TaskBody):
    """{handled: false} when the sentence is not a task (the app then asks the chat AI)."""
    return await run_in_threadpool(runner.handle, body.text, body.lang if body.lang in ("en", "de") else "en")


@router.get("/parse")
async def parse_only(text: str):
    return {"task": parse(text)}


@router.get("/status")
async def status():
    return runner.snapshot()
