"""
HTTP + WebSocket API for the operator joystick.

Can be mounted into the existing backend:

    from robot.teleop.teleop_api import create_teleop_router
    app.include_router(create_teleop_router(controller))

or run standalone with scripts/run_teleop_server.py.

Protocol (WebSocket /api/teleop/ws?token=...):
  client -> server, about every 100 ms while the screen is open:
    {"type": "cmd", "x": 0.4, "y": 0.0, "yaw": -0.2, "scale": 1.0}
    {"type": "stop"}
    {"type": "ping"}
  server -> client, about every 200 ms:
    {"type": "status", ...TeleopController.status()...}
    {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from robot.teleop.teleop_controller import (
    GESTURES,
    InvalidToken,
    LeaseBusy,
    PinLockedOut,
    PinRejected,
    TeleopController,
    TeleopError,
)

STATUS_PERIOD = 0.2


class UnlockRequest(BaseModel):
    pin: str
    operator: str = "operator"


class TokenRequest(BaseModel):
    token: str


class GestureRequest(BaseModel):
    token: str
    gesture: str


class VisitorGestureRequest(BaseModel):
    gesture: str


class DemoModeRequest(BaseModel):
    token: str
    enabled: bool


class ModeRequest(BaseModel):
    token: str
    mode: str  # "damp" | "stand_up" | "walk"


def _http_error(exc: TeleopError) -> HTTPException:
    if isinstance(exc, PinLockedOut):
        return HTTPException(429, str(exc))
    if isinstance(exc, LeaseBusy):
        return HTTPException(409, str(exc))
    if isinstance(exc, (PinRejected, InvalidToken)):
        return HTTPException(401, str(exc))
    return HTTPException(400, str(exc))


def create_teleop_router(controller: TeleopController) -> APIRouter:
    router = APIRouter(prefix="/api/teleop", tags=["teleop"])

    @router.get("/status")
    def status(x_teleop_token: str | None = Header(default=None)):
        return controller.status(x_teleop_token)

    @router.post("/unlock")
    def unlock(req: UnlockRequest):
        try:
            token = controller.unlock(req.pin, req.operator)
        except TeleopError as exc:
            raise _http_error(exc) from exc
        return {"token": token, "status": controller.status(token)}

    @router.post("/lock")
    def lock(req: TokenRequest):
        try:
            controller.lock(req.token)
        except TeleopError as exc:
            raise _http_error(exc) from exc
        return controller.status()

    # Stop and E-stop deliberately need no token: anyone may stop the robot.
    @router.post("/stop")
    def stop():
        controller.stop()
        return controller.status()

    @router.post("/estop")
    def estop():
        controller.estop("operator")
        return controller.status()

    @router.post("/estop/reset")
    def reset_estop(req: TokenRequest):
        try:
            controller.reset_estop(req.token)
        except TeleopError as exc:
            raise _http_error(exc) from exc
        return controller.status(req.token)

    @router.post("/mode")
    async def set_mode(req: ModeRequest):
        try:
            await asyncio.to_thread(
                controller.request_mode, req.token, req.mode
            )
        except TeleopError as exc:
            raise _http_error(exc) from exc
        return controller.status(req.token)

    @router.get("/gestures")
    def gestures():
        return [
            {"key": key, "label": label, "action_id": action_id}
            for key, (action_id, label) in GESTURES.items()
        ]

    @router.post("/gesture")
    def gesture(req: GestureRequest):
        try:
            controller.perform_gesture(req.token, req.gesture)
        except TeleopError as exc:
            raise _http_error(exc) from exc
        return controller.status(req.token)

    # ---- Visitor "Robot Show" (no PIN; operator must enable demo mode) ----

    @router.get("/demo")
    def demo_status():
        return controller.demo_status()

    @router.post("/demo/gesture")
    def demo_gesture(req: VisitorGestureRequest):
        try:
            controller.visitor_gesture(req.gesture)
        except TeleopError as exc:
            raise HTTPException(409, str(exc)) from exc
        return controller.demo_status()

    @router.post("/voice/gesture")
    def voice_gesture(req: VisitorGestureRequest):
        """Gesture from the Talk to G1 screen (adds handshake, high five)."""
        try:
            controller.visitor_gesture(req.gesture, by_voice=True)
        except TeleopError as exc:
            raise HTTPException(409, str(exc)) from exc
        return controller.demo_status()

    @router.post("/demo/mode")
    def demo_mode(req: DemoModeRequest):
        try:
            controller.set_demo_mode(req.token, req.enabled)
        except TeleopError as exc:
            raise _http_error(exc) from exc
        return controller.status(req.token)

    @router.websocket("/ws")
    async def teleop_ws(websocket: WebSocket, token: str = ""):
        await websocket.accept()

        if not controller.is_token_valid(token):
            await websocket.send_json(
                {"type": "error", "message": "Not authorized."}
            )
            await websocket.close(code=4401)
            return

        async def send_status() -> None:
            while True:
                await websocket.send_json(
                    {"type": "status", **controller.status(token)}
                )
                await asyncio.sleep(STATUS_PERIOD)

        sender = asyncio.create_task(send_status())
        try:
            while True:
                msg = await websocket.receive_json()
                kind = msg.get("type") if isinstance(msg, dict) else None
                try:
                    if kind == "cmd":
                        controller.command(
                            token,
                            float(msg.get("x", 0.0)),
                            float(msg.get("y", 0.0)),
                            float(msg.get("yaw", 0.0)),
                            float(msg.get("scale", 1.0)),
                        )
                    elif kind == "stop":
                        await asyncio.to_thread(controller.stop)
                        controller.touch(token)
                    elif kind == "ping":
                        controller.touch(token)
                    else:
                        await websocket.send_json(
                            {"type": "error",
                             "message": f"Unknown message: {kind}"}
                        )
                except InvalidToken:
                    await websocket.send_json(
                        {"type": "error",
                         "message": "Session expired. Unlock again."}
                    )
                    await websocket.close(code=4401)
                    return
                except (TeleopError, ValueError, TypeError) as exc:
                    await websocket.send_json(
                        {"type": "error", "message": str(exc)}
                    )
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            with contextlib.suppress(BaseException):
                await sender
            # Connection gone -> robot stops, whatever the reason.
            await asyncio.to_thread(controller.stop)

    return router
