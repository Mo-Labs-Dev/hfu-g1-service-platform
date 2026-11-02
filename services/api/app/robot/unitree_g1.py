from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from app.robot.base import BaseRobot


class UnitreeG1(BaseRobot):
    """
    Physical G1 adapter.

    FastAPI -> existing Unitree HTTP bridge -> robot SDK.

    This class never initializes the Unitree SDK directly.
    Unsupported autonomous actions fail closed.
    """

    def __init__(self) -> None:
        self.bridge_url = os.getenv(
            "G1_BRIDGE_URL",
            "http://127.0.0.1:8767",
        ).rstrip("/")

        self.bridge_token = os.getenv("G1_BRIDGE_TOKEN", "")
        self.connected = False

    def _request_sync(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )

        headers = {"Accept": "application/json"}

        if body is not None:
            headers["Content-Type"] = "application/json"

        if self.bridge_token:
            headers["X-G1-Bridge-Token"] = self.bridge_token

        request = urllib.request.Request(
            f"{self.bridge_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=5.0,
            ) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Bridge HTTP {error.code}: {detail}"
            ) from error

        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Unitree bridge unavailable: {error.reason}"
            ) from error

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_sync,
            method,
            path,
            payload,
        )

    async def connect(self) -> bool:
        try:
            health = await self._request("GET", "/health")
            self.connected = health.get("status") == "ok"
        except Exception:
            self.connected = False

        return self.connected

    async def disconnect(self) -> None:
        self.connected = False

    async def get_status(self) -> dict[str, Any]:
        try:
            status = await self._request("GET", "/status")
            status["mode"] = "physical"
            self.connected = bool(status.get("connected"))
            return status
        except Exception as error:
            self.connected = False
            return {
                "connected": False,
                "mode": "physical",
                "error": str(error),
            }

    async def get_motion_status(self) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/physical-motion/status",
        )

    async def arm_motion(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/physical-motion/arm",
            {"confirmed": True},
        )

    async def disarm_motion(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/physical-motion/disarm",
        )

    async def stop_motion(self) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/physical-motion/stop",
        )

    async def navigate(self, location_id: str) -> bool:
        # Autonomous navigation is not implemented yet.
        return False

    async def detect_object(self, object_name: str) -> bool:
        return False

    async def pick(self, object_name: str) -> bool:
        return False

    async def place(self, target: str) -> bool:
        return False

    async def manipulate(
        self,
        target: str,
        operation: str,
    ) -> bool:
        return False

    async def clean(self, target: str) -> bool:
        return False

    async def speak(self, text: str) -> bool:
        return False

    async def verify(
        self,
        target: str,
        condition: str,
    ) -> bool:
        return False

    async def return_home(self) -> bool:
        return False

    async def stop(self) -> bool:
        try:
            result = await self.stop_motion()
            # SDK acknowledgment is not physical stop verification.
            return result.get("status") == "stop_acknowledged"
        except Exception:
            return False