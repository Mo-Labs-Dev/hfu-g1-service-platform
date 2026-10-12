from __future__ import annotations

from copy import deepcopy
from typing import Any


# ============================================================
# DEFAULT LOCATIONS
# ============================================================
#
# These are semantic locations used by robot workflows.
#
# IMPORTANT:
# x, y and yaw intentionally remain None until the physical
# Unitree G1 is calibrated inside the HFU laboratory.
#
# We do not invent navigation coordinates.
# ============================================================

_LOCATIONS: list[dict[str, Any]] = [
    {
        "id": "home",
        "name": "Home Position",
        "target": "home",
        "description": (
            "Default safe position used before and after "
            "robot workflows."
        ),
        "type": "home",
        "x": None,
        "y": None,
        "yaw": None,
        "configured": False,
    },
    {
        "id": "coffee-station",
        "name": "Coffee Machine",
        "target": "coffee_station",
        "description": (
            "Customer assistance location for the coffee "
            "machine demonstration."
        ),
        "type": "interaction",
        "x": None,
        "y": None,
        "yaw": None,
        "configured": False,
    },
    {
        "id": "printer-station",
        "name": "3D Printer Room",
        "target": "printer_station",
        "description": (
            "Navigation and manipulation target for the "
            "3D printing assistance workflow."
        ),
        "type": "workstation",
        "x": None,
        "y": None,
        "yaw": None,
        "configured": False,
    },
    {
        "id": "cleaning-area",
        "name": "Cleaning Area",
        "target": "cleaning_area",
        "description": (
            "Demonstration area used by the autonomous "
            "cleaning workflow."
        ),
        "type": "workstation",
        "x": None,
        "y": None,
        "yaw": None,
        "configured": False,
    },
    {
        "id": "window-station",
        "name": "Window Station",
        "target": "window_station",
        "description": (
            "Navigation target used for the window "
            "assistance demonstration."
        ),
        "type": "interaction",
        "x": None,
        "y": None,
        "yaw": None,
        "configured": False,
    },
    {
        "id": "pick-place-station",
        "name": "Pick & Place Station",
        "target": "pick_place_station",
        "description": (
            "Object manipulation area used for reusable "
            "pick-and-place tasks."
        ),
        "type": "workstation",
        "x": None,
        "y": None,
        "yaw": None,
        "configured": False,
    },
]


# ============================================================
# READ
# ============================================================


def get_locations() -> list[dict[str, Any]]:
    """
    Return all configured semantic robot locations.

    deepcopy prevents API/service code from accidentally
    modifying the internal location store.
    """

    return deepcopy(_LOCATIONS)


def get_location(location_id: str) -> dict[str, Any] | None:
    """
    Find a location using its internal ID.
    """

    for location in _LOCATIONS:
        if location["id"] == location_id:
            return deepcopy(location)

    return None


def get_location_by_target(
    target: str,
) -> dict[str, Any] | None:
    """
    Find a location using its semantic target.

    Example:
        coffee_station
        printer_station
        home
    """

    for location in _LOCATIONS:
        if location["target"] == target:
            return deepcopy(location)

    return None


# ============================================================
# CREATE
# ============================================================


def create_location(
    location: dict[str, Any],
) -> dict[str, Any]:
    """
    Add a new semantic location.
    """

    if get_location(location["id"]) is not None:
        raise ValueError(
            f"Location '{location['id']}' already exists."
        )

    if (
        get_location_by_target(location["target"])
        is not None
    ):
        raise ValueError(
            f"Target '{location['target']}' already exists."
        )

    stored_location = deepcopy(location)

    _LOCATIONS.append(stored_location)

    return deepcopy(stored_location)


# ============================================================
# UPDATE
# ============================================================


def update_location(
    location_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Update an existing location.
    """

    for index, location in enumerate(_LOCATIONS):
        if location["id"] != location_id:
            continue

        updated_location = {
            **location,
            **deepcopy(updates),
        }

        updated_location["id"] = location_id

        _LOCATIONS[index] = updated_location

        return deepcopy(updated_location)

    return None


# ============================================================
# DELETE
# ============================================================


def delete_location(location_id: str) -> bool:
    """
    Delete a semantic location.
    """

    for index, location in enumerate(_LOCATIONS):
        if location["id"] == location_id:
            del _LOCATIONS[index]
            return True

    return False