from pydantic import BaseModel, Field

from app.models.task import TaskStep


class Demonstration(BaseModel):
    id: str
    name: str
    description: str

    location_id: str | None = None

    steps: list[TaskStep] = Field(
        default_factory=list
    )

    enabled: bool = True