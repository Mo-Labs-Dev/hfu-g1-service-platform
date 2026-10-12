
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.tasks.actions import ActionType


class WorkflowStepWrite(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=150,
    )

    action: ActionType

    parameters: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Step name cannot be empty.")

        return value

    @model_validator(mode="after")
    def validate_parameters(self):
        required = {
            ActionType.NAVIGATE: ("location_id",),
            ActionType.DETECT_OBJECT: ("object_name",),
            ActionType.PICK: ("object_name",),
            ActionType.PLACE: ("target",),
            ActionType.MANIPULATE: ("target", "operation"),
            ActionType.CLEAN: ("target",),
            ActionType.SPEAK: ("text",),
            ActionType.VERIFY: ("target", "condition"),
        }

        for key in required.get(self.action, ()):
            value = self.parameters.get(key)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Action '{self.action.value}' requires "
                    f"a non-empty '{key}' parameter."
                )

        if self.action == ActionType.WAIT:
            seconds = self.parameters.get("seconds", 1)

            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, (int, float))
                or not 0 <= seconds <= 300
            ):
                raise ValueError(
                    "WAIT seconds must be between 0 and 300."
                )

        return self


class WorkflowWrite(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=150,
    )

    description: str = Field(
        default="",
        max_length=2000,
    )

    status: Literal["draft", "ready"] = "draft"

    steps: list[WorkflowStepWrite] = Field(
        default_factory=list,
        max_length=100,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Workflow name cannot be empty."
            )

        return value


class WorkflowStepResponse(BaseModel):
    id: str
    position: int
    name: str
    action: ActionType
    parameters: dict[str, Any]


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str
    status: Literal["draft", "ready"]
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepResponse]
