"""Physical navigation goal adapter for the existing G1 workflow.

No motor control is implemented here. This is an API integration boundary:
physical goals require a separately validated Nav2 goal service, and fail
closed if it is absent or disabled. Never interpret goal acceptance as arrival.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

from app.db.database import AsyncSessionLocal
from app.services.navigation_service import navigation_service


class PhysicalNavigationService:
    def __init__(self) -> None:
        self.url = os.getenv("G1_NAV2_GOAL_BRIDGE_URL", "").rstrip("/")
        self.token = os.getenv("G1_NAV2_GOAL_BRIDGE_TOKEN", "")
        self.timeout_s = 10.0

    async def navigate(self, location_id: str) -> bool:
        if os.getenv("G1_PHYSICAL_NAVIGATION_ENABLED", "0") != "1":
            raise RuntimeError("Physical navigation is locked by configuration")
        if not self.url or not self.token:
            raise RuntimeError("Authenticated Nav2 goal bridge is not configured")

        async with AsyncSessionLocal() as session:
            target = await navigation_service.resolve_navigation_target(
                session, location_id
            )

        x, y, yaw = (target.get(k) for k in ("x", "y", "yaw"))
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (x, y, yaw)):
            raise ValueError("Navigation destination has invalid coordinates")

        payload = {"target": location_id, "x": x, "y": y, "yaw": yaw}
        result = await asyncio.to_thread(self._post, "/navigate", payload)
        # Only a confirmed action result means arrival, not HTTP 200 or accepted.
        return result.get("status") == "succeeded" and result.get("arrived") is True

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-G1-Nav-Token": self.token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data = json.load(response)
                if not isinstance(data, dict):
                    raise RuntimeError("Invalid Nav2 bridge response")
                return data
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Nav2 bridge unavailable: {exc}") from exc

    async def cancel(self) -> None:
        if self.url and self.token:
            await asyncio.to_thread(self._post, "/cancel", {})


physical_navigation_service = PhysicalNavigationService()
