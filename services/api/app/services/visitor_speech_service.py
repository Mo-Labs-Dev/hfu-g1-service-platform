from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi.concurrency import run_in_threadpool

from app.services.visitor_welcome_service import (
    visitor_welcome_service,
)

logger = logging.getLogger(__name__)


class VisitorSpeechService:
    def __init__(self) -> None:
        self.speech_url = os.getenv(
            "G1_SPEECH_URL",
            "http://127.0.0.1:8766/speak",
        )
        self.poll_interval = 0.25
        self.timeout_seconds = 15.0

        self.task: asyncio.Task | None = None
        self.handled_sessions: set[str] = set()

        self.last_session_id: str | None = None
        self.last_status = "idle"
        self.last_error: str | None = None
        self.last_response: dict[str, Any] | None = None
        self.last_attempt_at: str | None = None
        self.requests_accepted = 0
        self.requests_failed = 0

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _send_speech(self, text: str) -> dict[str, Any]:
        if not text.strip():
            raise ValueError("Welcome text is empty")

        payload = json.dumps({
            "text": text,
        }).encode("utf-8")

        request = Request(
            self.speech_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = response.read(4096)
                result = json.loads(body)

                if not isinstance(result, dict):
                    raise ValueError(
                        "Invalid speech bridge response"
                    )

                if result.get("accepted") is not True:
                    raise RuntimeError(
                        "Speech bridge did not accept request"
                    )

                return result

        except HTTPError as error:
            body = error.read(4096).decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"Speech bridge HTTP {error.code}: {body}"
            ) from error

        except URLError as error:
            raise RuntimeError(
                f"Speech bridge unavailable: {error.reason}"
            ) from error

    async def _run(self) -> None:
        logger.info("Visitor speech dispatcher started")

        try:
            while True:
                status = await visitor_welcome_service.status()

                session_id = status.get("session_id")
                state = status.get("state")

                if (
                    status.get("enabled")
                    and state == "welcoming"
                    and session_id
                    and session_id not in self.handled_sessions
                ):
                    # Reserve this session before the HTTP call
                    # to prevent duplicate greetings.
                    self.handled_sessions.add(session_id)

                    self.last_session_id = session_id
                    self.last_status = "sending"
                    self.last_error = None
                    self.last_response = None
                    self.last_attempt_at = self._timestamp()

                    try:
                        result = await run_in_threadpool(
                            self._send_speech,
                            status["welcome_text"],
                        )

                        self.last_response = result
                        self.last_status = "accepted"
                        self.requests_accepted += 1

                        logger.info(
                            "G1 accepted visitor greeting "
                            "for session %s",
                            session_id,
                        )

                    except asyncio.CancelledError:
                        raise

                    except Exception as error:
                        self.last_status = "failed"
                        self.last_error = str(error)
                        self.requests_failed += 1

                        logger.error(
                            "Visitor greeting failed "
                            "for session %s: %s",
                            session_id,
                            error,
                        )

                await asyncio.sleep(self.poll_interval)

        except asyncio.CancelledError:
            logger.info("Visitor speech dispatcher stopped")
            raise

    async def start(self) -> None:
        if self.task is not None and not self.task.done():
            return

        self.task = asyncio.create_task(
            self._run(),
            name="g1-visitor-speech",
        )

    async def stop(self) -> None:
        if self.task is None:
            return

        self.task.cancel()

        try:
            await self.task
        except asyncio.CancelledError:
            pass

        self.task = None

    def status(self) -> dict[str, Any]:
        return {
            "running": (
                self.task is not None
                and not self.task.done()
            ),
            "speech_bridge": self.speech_url,
            "last_session_id": self.last_session_id,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_response": self.last_response,
            "last_attempt_at": self.last_attempt_at,
            "requests_accepted": self.requests_accepted,
            "requests_failed": self.requests_failed,
            "playback_completion_verified": False,
        }


visitor_speech_service = VisitorSpeechService()