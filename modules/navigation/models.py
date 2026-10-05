from dataclasses import dataclass
from enum import Enum


class NavigationStatus(Enum):
    IDLE = "idle"
    NAVIGATING = "navigating"
    ARRIVED = "arrived"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class NavigationGoal:
    name: str
    x: float
    y: float
    yaw: float = 0.0
