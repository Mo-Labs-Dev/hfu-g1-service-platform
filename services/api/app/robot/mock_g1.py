import asyncio
from typing import Any

from app.robot.base import BaseRobot


class MockG1(BaseRobot):

    def __init__(self):
        self.connected = False
        self.battery = 87
        self.mode = "simulation"
        self.current_location = "home"
        self.current_action = "idle"

    async def connect(self) -> bool:
        await asyncio.sleep(0.5)

        self.connected = True
        self.current_action = "idle"

        print("[MockG1] Connected")

        return True

    async def disconnect(self) -> None:
        self.connected = False
        self.current_action = "offline"

        print("[MockG1] Disconnected")

    async def get_status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "battery": self.battery,
            "mode": self.mode,
            "location": self.current_location,
            "action": self.current_action,
        }

    async def navigate(self, location_id: str) -> bool:
        self.current_action = f"navigating:{location_id}"

        print(f"[MockG1] Navigating to {location_id}")

        await asyncio.sleep(2)

        self.current_location = location_id
        self.current_action = "idle"

        return True

    async def detect_object(self, object_name: str) -> bool:
        self.current_action = f"detecting:{object_name}"

        print(f"[MockG1] Detecting {object_name}")

        await asyncio.sleep(1)

        self.current_action = "idle"

        return True

    async def pick(self, object_name: str) -> bool:
        self.current_action = f"picking:{object_name}"

        print(f"[MockG1] Picking {object_name}")

        await asyncio.sleep(1.5)

        self.current_action = "idle"

        return True

    async def place(self, target: str) -> bool:
        self.current_action = f"placing:{target}"

        print(f"[MockG1] Placing object at {target}")

        await asyncio.sleep(1.5)

        self.current_action = "idle"

        return True

    async def manipulate(
        self,
        target: str,
        operation: str,
    ) -> bool:

        self.current_action = f"{operation}:{target}"

        print(
            f"[MockG1] Performing '{operation}' "
            f"on '{target}'"
        )

        await asyncio.sleep(1.5)

        self.current_action = "idle"

        return True

    async def clean(self, target: str) -> bool:
        self.current_action = f"cleaning:{target}"

        print(f"[MockG1] Cleaning {target}")

        await asyncio.sleep(2)

        self.current_action = "idle"

        return True

    async def speak(self, text: str) -> bool:
        self.current_action = "speaking"

        print(f"[MockG1] Says: {text}")

        await asyncio.sleep(1)

        self.current_action = "idle"

        return True

    async def verify(
        self,
        target: str,
        condition: str,
    ) -> bool:

        self.current_action = f"verifying:{target}"

        print(
            f"[MockG1] Verifying '{condition}' "
            f"for '{target}'"
        )

        await asyncio.sleep(1)

        self.current_action = "idle"

        return True

    async def return_home(self) -> bool:
        self.current_action = "returning_home"

        print("[MockG1] Returning home")

        await asyncio.sleep(2)

        self.current_location = "home"
        self.current_action = "idle"

        return True

    async def stop(self) -> bool:
        self.current_action = "stopped"

        print("[MockG1] STOP")

        return True