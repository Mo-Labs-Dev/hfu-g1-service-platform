from pydantic import BaseModel


class Location(BaseModel):
    id: str
    name: str
    description: str = ""

    x: float | None = None
    y: float | None = None
    yaw: float | None = None