from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.visitor_welcome_service import (
    visitor_welcome_service,
)

router = APIRouter(
    prefix="/api/visitor-welcome",
    tags=["Visitor Welcome"],
)


class ModeRequest(BaseModel):
    enabled: bool


class DetectionRequest(BaseModel):
    person_detected: bool


class AdvanceRequest(BaseModel):
    session_id: str = Field(min_length=1)
    action: Literal[
        "welcome_completed",
        "briefing_completed",
        "acknowledge_safety",
        "complete_session",
    ]


@router.get("/status")
async def welcome_status():
    return await visitor_welcome_service.status()


@router.post("/mode")
async def change_welcome_mode(request: ModeRequest):
    return await visitor_welcome_service.set_enabled(
        request.enabled
    )


@router.post("/detection")
async def report_detection(request: DetectionRequest):
    return await visitor_welcome_service.observe_person(
        request.person_detected
    )


@router.post("/manual")
async def manual_welcome():
    try:
        return await visitor_welcome_service.manual_welcome()
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error


@router.post("/advance")
async def advance_welcome(request: AdvanceRequest):
    try:
        return await visitor_welcome_service.advance(
            request.session_id,
            request.action,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error


@router.post("/reset")
async def reset_welcome():
    return await visitor_welcome_service.reset_session()


@router.get("/events")
async def welcome_events(after_id: int = 0):
    return {
        "events": await visitor_welcome_service.get_events(
            after_id
        )
    }