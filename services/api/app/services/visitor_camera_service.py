from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
from urllib.request import Request, urlopen

from fastapi.concurrency import run_in_threadpool

from app.services.vision_service import vision_service
from app.services.visitor_welcome_service import (
    visitor_welcome_service,
)

logger = logging.getLogger(__name__)


class VisitorCameraService:
    def __init__(self) -> None:
        self.snapshot_url = os.getenv(
            "G1_VISITOR_CAMERA_SNAPSHOT_URL",
            "http://127.0.0.1:8770/snapshot",
        )
        self.confidence = 0.45
        self.interval_seconds = 0.5
        self.timeout_seconds = 3.0
        self.max_image_bytes = 10 * 1024 * 1024

        self.task: asyncio.Task | None = None
        self.running = False
        self.last_error: str | None = None
        self.last_detection_at: float | None = None
        self.last_person_count = 0
        self.frames_processed = 0

    def _fetch_snapshot(self) -> bytes:
        request = Request(
            self.snapshot_url,
            headers={
                "Accept": "image/jpeg",
                "Cache-Control": "no-cache",
                "User-Agent": "G1-Visitor-Welcome/1.0",
            },
        )

        with urlopen(
            request,
            timeout=self.timeout_seconds,
        ) as response:
            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            if "image/jpeg" not in content_type:
                raise ValueError(
                    f"Unexpected camera response: {content_type}"
                )

            data = response.read(
                self.max_image_bytes + 1
            )

            if not data:
                raise ValueError(
                    "Camera returned an empty image"
                )

            if len(data) > self.max_image_bytes:
                raise ValueError(
                    "Camera image exceeds size limit"
                )

            return data

    def _detect_people(
        self,
        image_bytes: bytes,
    ) -> list[dict[str, Any]]:
        result = vision_service.detect(
            image_bytes,
            confidence=self.confidence,
        )

        return [
            detection
            for detection in result["detections"]
            if detection["label"] == "person"
        ]

    async def _run(self) -> None:
        logger.info(
            "G1 visitor camera worker started: %s",
            self.snapshot_url,
        )

        try:
            while True:
                try:
                    status = (
                        await visitor_welcome_service.status()
                    )

                    if not status["enabled"]:
                        await asyncio.sleep(
                            self.interval_seconds
                        )
                        continue

                    # Continue observing during the welcome
                    # so the backend can detect visitor absence.
                    #
                    # Do not perform automatic visitor departure
                    # transitions during safety or other workflows.
                    should_observe = status["state"] in {
                        "waiting_for_visitor",
                        "detecting",
                        "welcoming",
                    }

                    if not should_observe:
                        await asyncio.sleep(
                            self.interval_seconds
                        )
                        continue

                    image_bytes = await run_in_threadpool(
                        self._fetch_snapshot
                    )

                    people = await run_in_threadpool(
                        self._detect_people,
                        image_bytes,
                    )

                    self.frames_processed += 1
                    self.last_person_count = len(people)
                    self.last_error = None

                    detected = bool(people)

                    if detected:
                        self.last_detection_at = (
                            time.monotonic()
                        )

                    previous_state = status["state"]
                    previous_session = status["session_id"]

                    new_status = (
                        await visitor_welcome_service.observe_person(
                            detected
                        )
                    )

                    if (
                        new_status["state"] == "welcoming"
                        and previous_state != "welcoming"
                    ):
                        logger.info(
                            "Visitor confirmed. Session: %s",
                            new_status["session_id"],
                        )

                    if (
                        previous_session is not None
                        and new_status["session_id"] is None
                    ):
                        logger.info(
                            "Visitor session ended automatically."
                        )

                except asyncio.CancelledError:
                    raise

                except Exception as error:
                    self.last_error = str(error)
                    self.last_person_count = 0

                    logger.warning(
                        "Visitor camera detection failed: %s",
                        error,
                    )

                    # Important:
                    # Do not report a camera error as a
                    # confirmed absence. Otherwise a temporary
                    # camera outage could close a visitor session.

                await asyncio.sleep(
                    self.interval_seconds
                )

        except asyncio.CancelledError:
            logger.info(
                "G1 visitor camera worker stopped"
            )
            raise

    async def start(self) -> None:
        if self.task is not None and not self.task.done():
            return

        self.running = True
        self.task = asyncio.create_task(
            self._run(),
            name="g1-visitor-camera",
        )

    async def stop(self) -> None:
        self.running = False

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
            "camera_source": self.snapshot_url,
            "model": vision_service.model_name,
            "person_confidence_threshold": self.confidence,
            "frames_processed": self.frames_processed,
            "last_person_count": self.last_person_count,
            "last_error": self.last_error,
            "last_person_detection_seconds_ago": (
                round(
                    time.monotonic()
                    - self.last_detection_at,
                    1,
                )
                if self.last_detection_at is not None
                else None
            ),
        }


visitor_camera_service = VisitorCameraService()