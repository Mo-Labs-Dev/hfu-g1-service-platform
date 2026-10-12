
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.data.locations import get_locations
from app.db.database import AsyncSessionLocal, close_database
from app.db.models import Location


async def seed_locations() -> None:
    defaults = get_locations()

    created = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for item in defaults:
                existing = await session.scalar(
                    select(Location).where(
                        Location.id == item["id"]
                    )
                )

                if existing is not None:
                    skipped += 1
                    print(
                        f"SKIPPED: {item['name']}"
                    )
                    continue

                existing_target = await session.scalar(
                    select(Location).where(
                        Location.target == item["target"]
                    )
                )

                if existing_target is not None:
                    skipped += 1
                    print(
                        f"SKIPPED TARGET: {item['target']}"
                    )
                    continue

                location = Location(
                    id=item["id"],
                    name=item["name"],
                    target=item["target"],
                    description=item["description"],
                    location_type=item["type"],
                    x=item["x"],
                    y=item["y"],
                    yaw=item["yaw"],
                    configured=item["configured"],
                )

                session.add(location)
                created += 1

                print(
                    f"CREATED: {item['name']}"
                )

    print()
    print("G1 Studio Location Seed Complete")
    print(f"Created: {created}")
    print(f"Skipped: {skipped}")
    print(f"Total defaults: {len(defaults)}")


async def main() -> None:
    try:
        await seed_locations()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
