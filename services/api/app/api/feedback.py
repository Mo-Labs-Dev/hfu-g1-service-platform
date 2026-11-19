"""Visitor feedback API (app -> Studio Evaluation)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.services import feedback_service

router = APIRouter(prefix="/api/feedback", tags=["Feedback"])


class FeedbackBody(BaseModel):
    lang: str = "en"
    context: str = "general"
    rating: int | None = None
    recommend: str | None = None
    sus: list[int] | None = None
    comment: str = ""


@router.post("")
async def submit(body: FeedbackBody):
    try:
        return feedback_service.submit(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(429, str(exc))


@router.get("")
async def list_feedback():
    items = feedback_service.load()
    return {"items": list(reversed(items)), "stats": feedback_service.stats(items)}


@router.get("/export.csv")
async def export_csv():
    return Response(content=feedback_service.to_csv(feedback_service.load()), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="g1_visitor_feedback.csv"'})
