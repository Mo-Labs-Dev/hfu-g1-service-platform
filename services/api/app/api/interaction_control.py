"""Studio -> Interaction page: watch and steer every conversation with G1 (app, G1 microphone, Studio)."""
from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import interaction_control as ic
from app.services.interaction_service import G1_SPEECH_URL, OLLAMA_MODEL, OLLAMA_URL, interaction_service
from app.services.system_control import system_control

router = APIRouter(prefix="/api/interaction/control", tags=["Interaction control"])


def _pin(pin: str) -> None:
    try:
        system_control.check_pin(pin)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


class PinBody(BaseModel):
    pin: str = ""


class SettingsBody(BaseModel):
    pin: str = ""
    app_talk: bool | None = None
    speak_answers: bool | None = None
    reply_length: Literal["short", "normal", "long"] | None = None
    note: str | None = Field(default=None, max_length=ic.NOTE_MAX)


class SayBody(BaseModel):
    pin: str = ""
    text: str = Field(min_length=1, max_length=400)
    lang: Literal["en", "de"] = "en"
    show_in_app: bool = True
    gestures: bool = True


@router.get("/status")
async def status():
    from app.services import talk_gestures, voice_listener
    lst = voice_listener.get()
    if lst is None:
        voice = {"running": False}
    else:
        st = lst.state
        voice = {"running": True, "enabled": bool(st.get("enabled")), "mic": st.get("mic"),
                 "model": st.get("model"), "conversation": bool(st.get("conversation")),
                 "last_heard": st.get("last_heard"), "last_transcribe_s": st.get("last_transcribe_s"),
                 "last_wait_to_answer_s": st.get("last_wait_to_answer_s")}
    llm = {"model": OLLAMA_MODEL, "loaded": None}
    try:
        async with httpx.AsyncClient(timeout=1.5) as c:
            r = await c.get(f"{OLLAMA_URL}/api/ps")
            names = [m.get("name", "") for m in r.json().get("models", [])]
            llm["loaded"] = any(n.split(":")[0] == OLLAMA_MODEL.split(":")[0] for n in names)
            llm["ok"] = True
    except Exception:
        llm["ok"] = False
    return {
        "settings": ic.load_settings(),
        "stats": ic.stats(),
        "sessions": interaction_service.session_count(),
        "voice": voice,
        "gestures": talk_gestures.enabled(),
        "llm": llm,
    }


@router.put("/settings")
async def put_settings(body: SettingsBody):
    _pin(body.pin)
    try:
        return ic.save_settings(body.model_dump(exclude={"pin"}))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/log")
async def log(limit: int = 100):
    return {"items": ic.recent(limit)}


@router.post("/clear")
async def clear(body: PinBody):
    _pin(body.pin)
    ic.clear_view()
    return {"cleared": True}


@router.post("/reset-sessions")
async def reset_sessions(body: PinBody):
    """All visitors start fresh (G1 forgets names / context). Never touches robot motion."""
    _pin(body.pin)
    return {"reset": await interaction_service.reset_all()}


@router.post("/say")
async def say(body: SayBody):
    """G1 says the operator's sentence word for word (no AI)."""
    _pin(body.pin)
    text = " ".join(body.text.split())
    from app.services import talk_gestures, voice_listener
    lst = voice_listener.get()
    if lst is not None:
        lst.remember_reply(text)                     # G1 must not answer its own sentence
    ends = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{G1_SPEECH_URL}/speak", json={"text": text, "lang": body.lang})
            r.raise_for_status()
            res = r.json()
            if not res.get("accepted", True):
                raise HTTPException(409, res.get("detail") or "G1 is busy speaking - try again in a moment")
            ends = res.get("ends_in_ms") if isinstance(res.get("ends_in_ms"), int) else None
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Speech bridge not reachable: {exc}")
    if lst is not None:
        lst.mute_for(ends / 1000.0 if ends else lst.speech_seconds(text) + 0.5)
    if body.gestures:
        talk_gestures.gesture_for(text, ends)
    ic.record("operator", "", text, body.lang, None, spoke=True)
    if body.show_in_app:
        from app.api.websocket import manager
        await manager.broadcast({"type": "voice", "data": {"heard": "", "reply": text, "lang": body.lang,
                                                           "operator": True}})
    return {"spoken": True, "ends_in_ms": ends}


# ---------------------------------------------------------------- speaking cards (app "Try asking" buttons)
cards_router = APIRouter(prefix="/api/interaction/cards", tags=["Speaking cards"])


class CardsBody(BaseModel):
    pin: str = ""
    cards: list[dict]


@cards_router.get("")
async def cards_all():
    from app.services import talk_cards_service as tc
    d = tc.load()
    return {**d, "max_in_app": tc.MAX_IN_APP}


@cards_router.get("/app")
async def cards_for_app():
    """Only the switched-on cards, in app order (read by G1 Remote)."""
    from app.services import talk_cards_service as tc
    return tc.app_cards()


@cards_router.put("")
async def cards_save(body: CardsBody):
    from app.services import talk_cards_service as tc
    from app.api.websocket import manager
    _pin(body.pin)
    try:
        out = tc.save(body.cards)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {**out, "max_in_app": tc.MAX_IN_APP, "clients": len(manager.active_connections)}
