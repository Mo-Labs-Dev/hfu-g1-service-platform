from __future__ import annotations

import httpx

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.interaction_service import (
    interaction_service,
)


router = APIRouter(
    prefix="/api/interaction",
    tags=["Interaction"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    speak: bool = False


class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    speech_accepted: bool
    speech_error: str | None = None


@router.post("/ask", response_model=AskResponse)
async def ask_g1(request: AskRequest):
    try:
        return await interaction_service.ask(
            question=request.question,
            speak=request.speak,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
    except (httpx.HTTPError, RuntimeError) as error:
        print(f"[AI Interaction] {error}")
        raise HTTPException(
            status_code=503,
            detail="Local AI assistant is unavailable",
        ) from error