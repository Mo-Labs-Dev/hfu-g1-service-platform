from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.tasks.actions import ActionType


class TaskStatus(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStep(BaseModel):
    id: str
    name: str
    action: ActionType

    parameters: dict[str, Any] = Field(
        default_factory=dict
    )

    status: StepStatus = StepStatus.PENDING


class RobotTask(BaseModel):
    id: str
    name: str
    description: str = ""

    status: TaskStatus = TaskStatus.PENDING

    current_step: int = 0

    steps: list[TaskStep] = Field(
        default_factory=list
    )