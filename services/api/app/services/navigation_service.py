
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Location


class NavigationService:
    """Database-backed semantic location management."""

    async def list_locations(
        self,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        result = await session.scalars(
            select(Location).order_by(Location.name)
        )
        return [location.to_dict() for location in result.all()]

    async def get_location(
        self,
        session: AsyncSession,
        location_id: str,
    ) -> dict[str, Any] | None:
        location = await session.get(Location, location_id)
        return location.to_dict() if location else None

    async def get_target(
        self,
        session: AsyncSession,
        target: str,
    ) -> dict[str, Any] | None:
        location = await session.scalar(
            select(Location).where(Location.target == target)
        )
        return location.to_dict() if location else None

    async def add_location(
        self,
        session: AsyncSession,
        location: dict[str, Any],
    ) -> dict[str, Any]:
        record = Location(
            id=location["id"],
            name=location["name"],
            target=location["target"],
            description=location.get("description", ""),
            location_type=location.get("type", "navigation"),
            x=None,
            y=None,
            yaw=None,
            configured=False,
        )

        session.add(record)

        try:
            await session.commit()
            await session.refresh(record)
        except IntegrityError as error:
            await session.rollback()
            raise ValueError(
                "Location ID or target already exists."
            ) from error

        return record.to_dict()

    async def modify_location(
        self,
        session: AsyncSession,
        location_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        record = await session.get(Location, location_id)

        if record is None:
            return None

        field_mapping = {
            "name": "name",
            "target": "target",
            "description": "description",
            "type": "location_type",
        }

        for field, value in updates.items():
            if field not in field_mapping:
                continue
            setattr(record, field_mapping[field], value)

        try:
            await session.commit()
            await session.refresh(record)
        except IntegrityError as error:
            await session.rollback()
            raise ValueError(
                "Location ID or target already exists."
            ) from error

        return record.to_dict()

    async def configure_location(
        self,
        session: AsyncSession,
        location_id: str,
        x: float,
        y: float,
        yaw: float,
    ) -> dict[str, Any] | None:
        if not all(math.isfinite(v) for v in (x, y, yaw)):
            raise ValueError(
                "Calibration coordinates must be finite numbers."
            )

        record = await session.get(Location, location_id)

        if record is None:
            return None

        record.x = x
        record.y = y
        record.yaw = yaw
        record.configured = True

        await session.commit()
        await session.refresh(record)

        return record.to_dict()

    async def clear_calibration(
        self,
        session: AsyncSession,
        location_id: str,
    ) -> dict[str, Any] | None:
        record = await session.get(Location, location_id)

        if record is None:
            return None

        record.x = None
        record.y = None
        record.yaw = None
        record.configured = False

        await session.commit()
        await session.refresh(record)

        return record.to_dict()

    async def remove_location(
        self,
        session: AsyncSession,
        location_id: str,
    ) -> bool:
        record = await session.get(Location, location_id)

        if record is None:
            return False

        await session.delete(record)
        await session.commit()

        return True

    async def is_location_configured(
        self,
        session: AsyncSession,
        target: str,
    ) -> bool:
        location = await self.get_target(session, target)
        return bool(location and location["configured"])

    async def resolve_navigation_target(
        self,
        session: AsyncSession,
        target: str,
    ) -> dict[str, Any]:
        location = await self.get_target(session, target)

        if location is None:
            raise ValueError(
                f"Unknown navigation target: {target}"
            )

        if not location["configured"]:
            raise ValueError(
                f"Navigation target '{target}' "
                "has not been calibrated."
            )

        return location


navigation_service = NavigationService()
