from abc import ABC, abstractmethod
from typing import Any


class BaseRobot(ABC):
    """
    Common interface for every robot implementation.

    MockG1:
        Used during development on the Mac.

    UnitreeG1:
        Used with the real G1 robot in the lab.
    """

    @abstractmethod
    async def connect(self) -> bool:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def navigate(self, location_id: str) -> bool:
        pass

    @abstractmethod
    async def detect_object(self, object_name: str) -> bool:
        pass

    @abstractmethod
    async def pick(self, object_name: str) -> bool:
        pass

    @abstractmethod
    async def place(self, target: str) -> bool:
        pass

    @abstractmethod
    async def manipulate(
        self,
        target: str,
        operation: str,
    ) -> bool:
        pass

    @abstractmethod
    async def clean(self, target: str) -> bool:
        pass

    @abstractmethod
    async def speak(self, text: str) -> bool:
        pass

    @abstractmethod
    async def verify(
        self,
        target: str,
        condition: str,
    ) -> bool:
        pass

    @abstractmethod
    async def return_home(self) -> bool:
        pass

    @abstractmethod
    async def stop(self) -> bool:
        pass