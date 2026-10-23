from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.robot.mock_g1 import MockG1
from app.services.visitor_speech_service import visitor_speech_service

logger = logging.getLogger(__name__)


class HybridG1(MockG1):
    """
    Workflow robot adapter:
    - Speech: physical G1 speech bridge
    - Navigation/manipulation: MockG1 simulation
    - Physical locomotion: never requested
    """

    def __init__(self) -> None:
        super().__init__()
        self.mode = "simulation"
        self.last_speech_error: str | None = None

    async def get_status(self) -> dict[str, Any]:
        status = await super().get_status()
        status["mode"] = "simulation"
        status["speech_mode"] = "physical"
        status["navigation_mode"] = "simulation"
        status["physical_motion_requested"] = False
        status["last_speech_error"] = self.last_speech_error
        return status

    async def speak(self, text: str) -> bool:
        if not text.strip():
            return False

        self.current_action = "physical_speech"
        self.last_speech_error = None

        try:
            result = await run_in_threadpool(
                visitor_speech_service._send_speech,
                text,
            )

            if result.get("accepted") is not True:
                raise RuntimeError(
                    "Physical speech bridge rejected the request."
                )

            logger.info(
                "G1 physical speech accepted: %s",
                text,
            )

            return True

        except asyncio.CancelledError:
            raise

        except Exception as error:
            self.last_speech_error = str(error)
            logger.error(
                "G1 physical speech failed: %s",
                error,
            )
            return False

        finally:
            self.current_action = "idle"