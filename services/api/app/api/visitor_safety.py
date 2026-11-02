from __future__ import annotations

import json
import os

import httpx
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/api/visitor-safety",
    tags=["Visitor Safety"],
)

G1_SPEECH_URL = os.getenv("G1_SPEECH_URL", "http://127.0.0.1:8766")

BRIEFING_VERSION = "hfu-original-curated15-draft-2026-10-22"

# The HFU source presentation is a general safety briefing.
# The condensed visitor briefing and robot-specific instructions
# must be approved by the responsible lab supervisor.
BRIEFING_APPROVED = False

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "visitor_safety.db"

_db_lock = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SLIDES = [{'id': 'welcome', 'number': 1, 'title': 'Original HFU safety briefing', 'subtitle': 'Overview of HFU safety information', 'points': ['Original HFU presentation slide 1', 'Overview of HFU safety information'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 1', 'original_slide_number': 1, 'image_resource': 'hfu_safety_01'}, {'id': 'overview', 'number': 2, 'title': 'Safety topics', 'subtitle': 'What the original training covers', 'points': ['Original HFU presentation slide 2', 'What the original training covers'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 2', 'original_slide_number': 2, 'image_resource': 'hfu_safety_02'}, {'id': 'fire_response', 'number': 3, 'title': 'Fire: immediate response', 'subtitle': 'Stay calm, warn others, call for help', 'points': ['Original HFU presentation slide 7', 'Stay calm, warn others, call for help'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 7', 'original_slide_number': 7, 'image_resource': 'hfu_safety_03'}, {'id': 'evacuation', 'number': 4, 'title': 'Evacuating the building', 'subtitle': 'Follow the marked escape routes', 'points': ['Original HFU presentation slide 8', 'Follow the marked escape routes'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 8', 'original_slide_number': 8, 'image_resource': 'hfu_safety_04'}, {'id': 'small_fires', 'number': 5, 'title': 'Small fires', 'subtitle': 'Only intervene if it is safe', 'points': ['Original HFU presentation slide 12', 'Only intervene if it is safe'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 12', 'original_slide_number': 12, 'image_resource': 'hfu_safety_05'}, {'id': 'extinguishers', 'number': 6, 'title': 'Fire extinguisher types', 'subtitle': 'Use the correct extinguishing agent', 'points': ['Original HFU presentation slide 13', 'Use the correct extinguishing agent'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 13', 'original_slide_number': 13, 'image_resource': 'hfu_safety_06'}, {'id': 'assembly', 'number': 7, 'title': 'Assembly points', 'subtitle': 'Know the location for your building', 'points': ['Original HFU presentation slide 15', 'Know the location for your building'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 15', 'original_slide_number': 15, 'image_resource': 'hfu_safety_07'}, {'id': 'accident_response', 'number': 8, 'title': 'Accident response', 'subtitle': 'Protect yourself and call for help', 'points': ['Original HFU presentation slide 16', 'Protect yourself and call for help'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 16', 'original_slide_number': 16, 'image_resource': 'hfu_safety_08'}, {'id': 'first_aid', 'number': 9, 'title': 'First aid', 'subtitle': 'Call trained helpers', 'points': ['Original HFU presentation slide 17', 'Call trained helpers'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 17', 'original_slide_number': 17, 'image_resource': 'hfu_safety_09'}, {'id': 'defibrillator', 'number': 10, 'title': 'Defibrillator', 'subtitle': 'Follow device instructions', 'points': ['Original HFU presentation slide 19', 'Follow device instructions'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 19', 'original_slide_number': 19, 'image_resource': 'hfu_safety_10'}, {'id': 'lab_access', 'number': 11, 'title': 'Laboratory access', 'subtitle': 'Enter and work only with permission', 'points': ['Original HFU presentation slide 22', 'Enter and work only with permission'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 22', 'original_slide_number': 22, 'image_resource': 'hfu_safety_11'}, {'id': 'lab_housekeeping', 'number': 12, 'title': 'Laboratory housekeeping', 'subtitle': 'Prevent hazards', 'points': ['Original HFU presentation slide 23', 'Prevent hazards'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 23', 'original_slide_number': 23, 'image_resource': 'hfu_safety_12'}, {'id': 'electrical', 'number': 13, 'title': 'Electrical equipment', 'subtitle': 'Do not interfere with electrical devices', 'points': ['Original HFU presentation slide 24', 'Do not interfere with electrical devices'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 24', 'original_slide_number': 24, 'image_resource': 'hfu_safety_13'}, {'id': 'waste', 'number': 14, 'title': 'Waste and hazardous materials', 'subtitle': 'Handle and dispose of materials correctly', 'points': ['Original HFU presentation slide 29', 'Handle and dispose of materials correctly'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 29', 'original_slide_number': 29, 'image_resource': 'hfu_safety_14'}, {'id': 'summary', 'number': 15, 'title': 'Key safety reminders', 'subtitle': 'Review before entering the lab', 'points': ['Original HFU presentation slide 34', 'Review before entering the lab'], 'source': '260930_Sicherheitsunterweisung_mitLabor_Droll.pptx — slide 34', 'original_slide_number': 34, 'image_resource': 'hfu_safety_15'}]


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=10,
    )
    connection.row_factory = sqlite3.Row

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS visitor_safety_sessions (
            session_id TEXT PRIMARY KEY,
            briefing_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            acknowledged_at TEXT,
            acknowledged_version TEXT,
            acknowledgement_details TEXT
        )
        """
    )
    connection.commit()

    return connection


class AcknowledgementRequest(BaseModel):
    understood: bool
    presented_slide_ids: list[str] = Field(
        default_factory=list,
    )


def load_session(session_id: str) -> dict:
    with _db_lock:
        connection = get_connection()
        try:
            row = connection.execute(
                """
                SELECT *
                FROM visitor_safety_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        finally:
            connection.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Visitor session not found",
        )

    result = dict(row)

    result["safety_acknowledged"] = (
        result["acknowledged_at"] is not None
        and result["acknowledged_version"] == BRIEFING_VERSION
    )

    return result


@router.get("/status")
def safety_status():
    return {
        "status": "ready",
        "service": "visitor-safety",
        "briefing_version": BRIEFING_VERSION,
        "slide_count": len(SLIDES),
        "briefing_approved": BRIEFING_APPROVED,
        "storage": "sqlite",
    }


@router.get("/briefing")
def get_briefing():
    return {
        "briefing_id": "hfu-visitor-safety",
        "version": BRIEFING_VERSION,
        "title": "HFU Laboratory Visitor Safety",
        "institute": (
            "Institute for Product and Service Engineering"
        ),
        "language": "en",
        "approval_status": (
            "approved" if BRIEFING_APPROVED
            else "draft_pending_lab_approval"
        ),
        "formal_training_replacement": False,
        "slides": SLIDES,
        "acknowledgement_required": True,
    }


@router.post("/sessions", status_code=201)
def create_session():
    session_id = str(uuid4())
    created_at = utc_now()

    with _db_lock:
        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO visitor_safety_sessions (
                    session_id,
                    briefing_version,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    session_id,
                    BRIEFING_VERSION,
                    created_at,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    return {
        "session_id": session_id,
        "created_at": created_at,
        "briefing_version": BRIEFING_VERSION,
        "safety_acknowledged": False,
        "next_step": "show_safety_briefing",
    }


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = load_session(session_id)

    return {
        "session_id": session["session_id"],
        "created_at": session["created_at"],
        "briefing_version": session["briefing_version"],
        "safety_acknowledged": session["safety_acknowledged"],
        "acknowledged_at": session["acknowledged_at"],
        "next_step": (
            "select_destination"
            if session["safety_acknowledged"]
            else "show_safety_briefing"
        ),
    }


@router.post("/sessions/{session_id}/acknowledge")
def acknowledge_safety(
    session_id: str,
    request: AcknowledgementRequest,
):
    load_session(session_id)

    if not request.understood:
        raise HTTPException(
            status_code=400,
            detail="Safety acknowledgement is required",
        )

    required_ids = {slide["id"] for slide in SLIDES}
    presented_ids = set(request.presented_slide_ids)

    if not required_ids.issubset(presented_ids):
        raise HTTPException(
            status_code=400,
            detail=(
                "All safety slides must be presented "
                "before acknowledgement"
            ),
        )

    acknowledged_at = utc_now()

    with _db_lock:
        connection = get_connection()
        try:
            connection.execute(
                """
                UPDATE visitor_safety_sessions
                SET
                    acknowledged_at = ?,
                    acknowledged_version = ?,
                    acknowledgement_details = ?
                WHERE session_id = ?
                """,
                (
                    acknowledged_at,
                    BRIEFING_VERSION,
                    json.dumps(
                        {
                            "understood": True,
                            "presented_slide_ids": sorted(
                                presented_ids
                            ),
                        }
                    ),
                    session_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    return {
        "session_id": session_id,
        "safety_acknowledged": True,
        "acknowledged_at": acknowledged_at,
        "briefing_version": BRIEFING_VERSION,
        "next_step": "select_destination",
        "note": (
            "Visitor acknowledgement recorded. "
            "Formal HFU safety requirements remain applicable."
        ),
    }


@router.get("/sessions/{session_id}/tour-eligibility")
def tour_eligibility(session_id: str):
    session = load_session(session_id)

    acknowledged = session["safety_acknowledged"]

    # Approval is a separate condition from acknowledgement.
    # Neither condition authorizes physical robot movement.
    eligible = acknowledged and BRIEFING_APPROVED

    return {
        "session_id": session_id,
        "destination": "coffee_machine",
        "safety_acknowledged": acknowledged,
        "briefing_approved": BRIEFING_APPROVED,
        "eligible_for_tour_request": eligible,
        "physical_motion_authorized": False,
        "reason": (
            "eligible_for_operator_review"
            if eligible
            else (
                "safety_acknowledgement_required"
                if not acknowledged
                else "lab_briefing_approval_required"
            )
        ),
    }


# Fixed, reviewable speech for each slide. These are visitor-briefing DRAFTS,
# not a substitute for formal HFU or laboratory-specific safety training.
SLIDE_NARRATION = {'welcome': 'Welcome to the HFU safety briefing. These are original university safety slides. This shortened visitor version highlights emergency procedures and laboratory rules. Please also follow the instructions of your laboratory host.', 'overview': 'The university safety training covers insurance, fires, first aid, electrical devices, information security, environmental protection, and respectful behavior. We will focus on topics relevant to a supervised laboratory visit.', 'fire_response': 'If there is a fire, stay calm and protect yourself. Protecting people comes before protecting property. Activate the fire alarm, call emergency services on one one two, and warn others when it is safe to do so.', 'evacuation': 'When a fire alarm sounds, leave the building immediately using the marked escape routes. Do not delay to collect belongings. Go to the designated assembly point and do not return until emergency personnel allow it.', 'small_fires': 'For a small fire, alert the fire service first. Only attempt to use an extinguisher if you are trained, the fire is small, and your escape route remains clear. Your personal safety comes first.', 'extinguishers': 'Different fires require different extinguishers. Follow the labels and pictograms. Never use water on burning cooking oil or energized electrical equipment. Do not take risks to save equipment.', 'assembly': 'Every HFU building has a designated assembly point. Check the posted escape and rescue plan for the building you are visiting. After evacuation, report to the assembly point and follow staff instructions.', 'accident_response': 'If an accident occurs, remain calm and avoid further danger. Alert laboratory staff and first aid personnel. In an emergency call one one two. For an electrical incident, use the emergency stop only when it is safe and appropriate.', 'first_aid': 'Check whether the injured person responds. Do not put yourself in danger. Call one one two if necessary, notify a first aider, and use the first aid equipment as instructed. Report the incident to university staff.', 'defibrillator': 'The original HFU slide identifies defibrillator locations in the C and I buildings. These locations may not apply to the laboratory you are visiting. Ask your host about the nearest defibrillator and follow the device voice instructions in an emergency.', 'lab_access': 'Laboratories and workshops require authorization and appropriate safety instruction. Do not work alone or operate equipment without permission. Read the laboratory rules and follow your host at all times.', 'lab_housekeeping': 'Work that produces smoke, dust, or fumes requires prior coordination because it may trigger fire alarms. Keep the workplace tidy, secure hazardous materials, and switch off equipment when instructed.', 'electrical': 'Electrical equipment includes computers, monitors, printers, and network devices. Use only equipment you have been authorized to operate. Report faults to staff and do not attempt electrical repairs yourself.', 'waste': 'Hazardous substances require special instructions for use and disposal. Do not touch unknown chemicals or containers. Keep materials labeled and dispose of waste only as directed by laboratory staff.', 'summary': 'Remember the essentials. Stay calm in an emergency, protect yourself, call one one two, follow escape routes, and report to the assembly point. Respect laboratory rules, equipment, and other people. Please ask your host if anything is unclear.'}


@router.post("/sessions/{session_id}/slides/{slide_id}/speak")
async def speak_safety_slide(session_id: str, slide_id: str):
    # Verify that the visitor session exists; never start a robot action.
    load_session(session_id)
    slide = next((item for item in SLIDES if item["id"] == slide_id), None)
    if slide is None:
        raise HTTPException(status_code=404, detail="Safety slide not found")

    narration = SLIDE_NARRATION.get(slide_id)
    if not narration:
        raise HTTPException(status_code=500, detail="Narration not configured")

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{G1_SPEECH_URL.rstrip('/')}/speak",
                json={"text": narration},
            )
            response.raise_for_status()
            accepted = response.json().get("accepted") is True
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=502, detail=f"G1 speech bridge unavailable: {error}"
        ) from error

    if not accepted:
        raise HTTPException(
            status_code=503, detail="G1 speech bridge did not accept narration"
        )

    # 'accepted' is NOT evidence that playback finished or the visitor listened.
    return {
        "session_id": session_id,
        "slide_id": slide_id,
        "slide_number": slide["number"],
        "speech_accepted": True,
        "speech_completed": False,
        "narration": narration,
        "briefing_approved": BRIEFING_APPROVED,
    }