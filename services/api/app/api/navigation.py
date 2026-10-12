
from __future__ import annotations

import math
import re
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.navigation_service import navigation_service


router = APIRouter(
    prefix="/api/locations",
    tags=["Locations"],
)

DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db),
]

LocationType = Literal[
    "home",
    "navigation",
    "workstation",
    "interaction",
]


class LocationResponse(BaseModel):
    id: str
    name: str
    target: str
    description: str
    type: LocationType
    x: float | None = None
    y: float | None = None
    yaw: float | None = None
    configured: bool = False


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    type: LocationType = "navigation"


class LocationUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    target: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    description: str | None = Field(
        default=None,
        max_length=500,
    )
    type: LocationType | None = None


class LocationCalibration(BaseModel):
    x: float
    y: float
    yaw: float


def create_location_id(name: str) -> str:
    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        name.strip().lower(),
    )
    return value.strip("-")


def normalize_target(target: str) -> str:
    value = re.sub(
        r"[^a-z0-9]+",
        "_",
        target.strip().lower(),
    )
    return value.strip("_")


def not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Location not found.",
    )


def conflict(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    )


@router.get(
    "",
    response_model=list[LocationResponse],
)
async def list_locations(
    db: DatabaseSession,
):
    return await navigation_service.list_locations(db)


@router.get(
    "/{location_id}",
    response_model=LocationResponse,
)
async def get_location(
    location_id: str,
    db: DatabaseSession,
):
    location = await navigation_service.get_location(
        db,
        location_id,
    )

    if location is None:
        raise not_found()

    return location


@router.post(
    "",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    payload: LocationCreate,
    db: DatabaseSession,
):
    name = payload.name.strip()
    target = normalize_target(payload.target)
    location_id = create_location_id(name)

    if not location_id or not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name and target must contain letters or numbers.",
        )

    location = {
        "id": location_id,
        "name": name,
        "target": target,
        "description": payload.description.strip(),
        "type": payload.type,
    }

    try:
        return await navigation_service.add_location(
            db,
            location,
        )
    except ValueError as error:
        raise conflict(error) from error


@router.put(
    "/{location_id}",
    response_model=LocationResponse,
)
async def update_location(
    location_id: str,
    payload: LocationUpdate,
    db: DatabaseSession,
):
    updates = payload.model_dump(exclude_unset=True)

    if "name" in updates:
        if updates["name"] is None or not updates["name"].strip():
            raise HTTPException(
                status_code=422,
                detail="Name cannot be empty.",
            )
        updates["name"] = updates["name"].strip()

    if "target" in updates:
        if updates["target"] is None:
            raise HTTPException(
                status_code=422,
                detail="Target cannot be null.",
            )
        updates["target"] = normalize_target(updates["target"])
        if not updates["target"]:
            raise HTTPException(
                status_code=422,
                detail="Target cannot be empty.",
            )

    if "description" in updates:
        if updates["description"] is None:
            raise HTTPException(
                status_code=422,
                detail="Description cannot be null.",
            )
        updates["description"] = updates["description"].strip()

    if "type" in updates and updates["type"] is None:
        raise HTTPException(
            status_code=422,
            detail="Location type cannot be null.",
        )

    try:
        location = await navigation_service.modify_location(
            db,
            location_id,
            updates,
        )
    except ValueError as error:
        raise conflict(error) from error

    if location is None:
        raise not_found()

    return location


@router.put(
    "/{location_id}/calibration",
    response_model=LocationResponse,
)
async def calibrate_location(
    location_id: str,
    payload: LocationCalibration,
    db: DatabaseSession,
):
    if not all(
        math.isfinite(value)
        for value in (payload.x, payload.y, payload.yaw)
    ):
        raise HTTPException(
            status_code=422,
            detail="Coordinates must be finite numbers.",
        )

    location = await navigation_service.configure_location(
        db,
        location_id,
        payload.x,
        payload.y,
        payload.yaw,
    )

    if location is None:
        raise not_found()

    return location


@router.delete(
    "/{location_id}/calibration",
    response_model=LocationResponse,
)
async def clear_location_calibration(
    location_id: str,
    db: DatabaseSession,
):
    location = await navigation_service.clear_calibration(
        db,
        location_id,
    )

    if location is None:
        raise not_found()

    return location


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_location(
    location_id: str,
    db: DatabaseSession,
):
    deleted = await navigation_service.remove_location(
        db,
        location_id,
    )

    if not deleted:
        raise not_found()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )
