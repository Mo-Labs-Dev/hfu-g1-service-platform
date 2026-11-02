from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class VisitorWelcomeService:
    CONFIRM_SECONDS = 2.0
    DETECTION_GAP_SECONDS = 1.5
    COOLDOWN_SECONDS = 5.0

    # Visitor must be absent this long before ending a visit.
    VISITOR_ABSENCE_SECONDS = 8.0

    # Allow greeting and Welcome page to finish before
    # automatically closing an unattended welcome session.
    WELCOME_GRACE_SECONDS = 15.0

    # Camera must be clear before rearming after a session.
    CLEAR_TO_REARM_SECONDS = 5.0

    # Fallback for abandoned sessions.
    SESSION_TIMEOUT_SECONDS = 180.0

    def __init__(self) -> None:
        self.lock = asyncio.Lock()

        # Automatically enable visitor detection at startup.
        # Only use this in a supervised, approved visitor area.
        self.enabled = True
        self.state = "waiting_for_visitor"
        self.session_id: str | None = None

        self.detected_since: float | None = None
        self.last_detection: float | None = None
        self.cooldown_until = 0.0

        self.session_started_at: float | None = None
        self.session_last_activity_at: float | None = None

        self.absent_since: float | None = None
        self.clear_since: float | None = None
        self.requires_clear = False

        self.updated_at = self._timestamp()
        self.event_id = 0
        self.events: list[dict[str, Any]] = []

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _create_safety_session(session_id: str) -> None:
        from app.api.visitor_safety import (
            BRIEFING_VERSION,
            _db_lock,
            get_connection,
            utc_now,
        )

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
                        utc_now(),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

    def _safety_acknowledged(self) -> bool:
        if not self.session_id:
            return False

        from app.api.visitor_safety import load_session

        try:
            session = load_session(self.session_id)
            return bool(session["safety_acknowledged"])
        except Exception:
            return False

    def _event(self, name: str) -> None:
        self.event_id += 1
        self.updated_at = self._timestamp()

        self.events.append({
            "id": self.event_id,
            "type": name,
            "state": self.state,
            "session_id": self.session_id,
            "timestamp": self.updated_at,
        })

        self.events = self.events[-100:]

    def _reset_internal(self, event_name: str) -> None:
        self.session_id = None
        self.detected_since = None
        self.last_detection = None
        self.session_started_at = None
        self.session_last_activity_at = None
        self.absent_since = None
        self.clear_since = None

        # Prevent rewelcoming someone who remains in view.
        self.requires_clear = True

        self.cooldown_until = (
            time.monotonic() + self.COOLDOWN_SECONDS
        )

        self.state = (
            "waiting_for_visitor" if self.enabled else "idle"
        )
        self._event(event_name)

    def _expire_inactive_session(self) -> None:
        if (
            self.session_id is None
            or self.session_last_activity_at is None
        ):
            return

        elapsed = (
            time.monotonic() - self.session_last_activity_at
        )

        if elapsed >= self.SESSION_TIMEOUT_SECONDS:
            self._reset_internal("session_expired")

    def _status(self) -> dict[str, Any]:
        now = time.monotonic()

        remaining_session_seconds = None
        if (
            self.session_id is not None
            and self.session_last_activity_at is not None
        ):
            remaining_session_seconds = round(
                max(
                    0.0,
                    self.SESSION_TIMEOUT_SECONDS
                    - (now - self.session_last_activity_at),
                ),
                1,
            )

        return {
            "enabled": self.enabled,
            "state": self.state,
            "session_id": self.session_id,
            "event_id": self.event_id,
            "updated_at": self.updated_at,
            "cooldown_remaining_seconds": round(
                max(0.0, self.cooldown_until - now), 1
            ),
            "session_timeout_remaining_seconds": (
                remaining_session_seconds
            ),
            "person_detection_active": (
                self.last_detection is not None
                and now - self.last_detection
                <= self.DETECTION_GAP_SECONDS
            ),
            "requires_clear": self.requires_clear,
            "visitor_absence_seconds": (
                round(now - self.absent_since, 1)
                if self.absent_since is not None
                else None
            ),
            "safety_acknowledged": self._safety_acknowledged(),
            "welcome_text": (
                "Hello! Welcome to the Institute for "
                "Product and Service Engineering. "
                "I'm G1, your robotic assistant. "
                "You can talk to me or explore the "
                "laboratory using the tablet."
            ),
        }

    async def status(self) -> dict[str, Any]:
        async with self.lock:
            self._expire_inactive_session()
            return self._status()

    async def set_enabled(
        self, enabled: bool
    ) -> dict[str, Any]:
        async with self.lock:
            self.enabled = enabled
            self.detected_since = None
            self.last_detection = None

            if not enabled:
                self.state = "idle"
                self.session_id = None
                self.session_started_at = None
                self.session_last_activity_at = None
                self.absent_since = None
                self.clear_since = None
                self.requires_clear = True
            elif self.state == "idle":
                self.state = "waiting_for_visitor"
                self.requires_clear = True
                self.clear_since = None

            self._event("welcome_mode_changed")
            return self._status()

    def _begin_welcome(self) -> None:
        session_id = str(uuid4())
        self._create_safety_session(session_id)

        now = time.monotonic()

        self.session_id = session_id
        self.session_started_at = now
        self.session_last_activity_at = now

        self.state = "welcoming"
        self.detected_since = None
        self.last_detection = now
        self.absent_since = None
        self.clear_since = None

        self._event("visitor_welcome_requested")

    async def observe_person(
        self, detected: bool
    ) -> dict[str, Any]:
        async with self.lock:
            self._expire_inactive_session()
            now = time.monotonic()

            if not self.enabled:
                return self._status()

            # Never interpret a failed camera read as absence.
            # This method must receive actual YOLO observations.

            if detected:
                self.absent_since = None
                self.clear_since = None
            else:
                if self.absent_since is None:
                    self.absent_since = now

            # Active safety and other visitor workflows must not
            # be terminated merely because someone moves away.
            if self.state not in {
                "waiting_for_visitor",
                "detecting",
                "welcoming",
            }:
                return self._status()

            # An active greeting remains available while the
            # visitor is present. Close it after confirmed absence.
            if self.state == "welcoming":
                session_age = (
                    now - self.session_started_at
                    if self.session_started_at is not None
                    else 0.0
                )

                absence_age = (
                    now - self.absent_since
                    if self.absent_since is not None
                    else 0.0
                )

                if (
                    not detected
                    and session_age >= self.WELCOME_GRACE_SECONDS
                    and absence_age >= self.VISITOR_ABSENCE_SECONDS
                ):
                    self._reset_internal("visitor_left")

                return self._status()

            # After a previous visit, the camera must observe
            # an empty scene before another greeting is allowed.
            if self.requires_clear:
                self.detected_since = None
                self.last_detection = None

                if detected:
                    self.clear_since = None
                    if self.state == "detecting":
                        self.state = "waiting_for_visitor"
                        self._event("detection_reset")
                    return self._status()

                if self.clear_since is None:
                    self.clear_since = now

                if (
                    now - self.clear_since
                    >= self.CLEAR_TO_REARM_SECONDS
                ):
                    self.requires_clear = False
                    self.clear_since = None
                    self._event("camera_rearmed")

                return self._status()

            if now < self.cooldown_until:
                return self._status()

            if not detected:
                if (
                    self.last_detection is None
                    or now - self.last_detection
                    > self.DETECTION_GAP_SECONDS
                ):
                    if self.state == "detecting":
                        self.state = "waiting_for_visitor"
                        self.detected_since = None
                        self._event("detection_reset")

                return self._status()

            if (
                self.last_detection is None
                or now - self.last_detection
                > self.DETECTION_GAP_SECONDS
            ):
                self.detected_since = now
                self.state = "detecting"
                self._event("person_detected")

            self.last_detection = now

            if (
                self.detected_since is not None
                and now - self.detected_since
                >= self.CONFIRM_SECONDS
            ):
                self._begin_welcome()

            return self._status()

    async def manual_welcome(self) -> dict[str, Any]:
        async with self.lock:
            self._expire_inactive_session()

            if not self.enabled:
                raise ValueError("Enable Welcome Mode first.")

            if self.state not in {
                "waiting_for_visitor",
                "detecting",
            }:
                raise ValueError(
                    "A visitor session is already active."
                )

            if self.requires_clear:
                raise ValueError(
                    "Camera must observe an empty visitor area "
                    "before another welcome."
                )

            if time.monotonic() < self.cooldown_until:
                raise ValueError(
                    "Welcome cooldown is active."
                )

            self._begin_welcome()
            return self._status()

    async def advance(
        self,
        session_id: str,
        action: str,
    ) -> dict[str, Any]:
        async with self.lock:
            self._expire_inactive_session()

            if not self.enabled:
                raise ValueError(
                    "Welcome Mode is disabled."
                )

            if (
                not self.session_id
                or session_id != self.session_id
            ):
                raise ValueError(
                    "Invalid or expired visitor session."
                )

            # Preserve the existing Android safety workflow.
            transitions = {
                (
                    "welcoming",
                    "welcome_completed",
                ): "safety_briefing",
                (
                    "safety_briefing",
                    "briefing_completed",
                ): "awaiting_acknowledgement",
                (
                    "awaiting_acknowledgement",
                    "acknowledge_safety",
                ): "ready",
                (
                    "ready",
                    "complete_session",
                ): "session_complete",
            }

            next_state = transitions.get(
                (self.state, action)
            )

            if next_state is None:
                raise ValueError(
                    f"Action '{action}' is not valid "
                    f"in state '{self.state}'."
                )

            if action == "acknowledge_safety":
                if not self._safety_acknowledged():
                    raise ValueError(
                        "Safety acknowledgement must first "
                        "be recorded by the Visitor Safety API."
                    )

            if action == "complete_session":
                self._reset_internal("session_completed")
                return self._status()

            self.state = next_state
            self.session_last_activity_at = time.monotonic()
            self.absent_since = None
            self._event(action)

            return self._status()

    async def reset_session(self) -> dict[str, Any]:
        async with self.lock:
            self._reset_internal("session_reset")
            return self._status()

    async def get_events(
        self,
        after_id: int = 0,
    ) -> list[dict[str, Any]]:
        async with self.lock:
            self._expire_inactive_session()
            return [
                event
                for event in self.events
                if event["id"] > after_id
            ]


visitor_welcome_service = VisitorWelcomeService()