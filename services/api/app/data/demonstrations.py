from app.models.demonstration import Demonstration
from app.models.task import TaskStep
from app.tasks.actions import ActionType


DEMONSTRATIONS = [
    Demonstration(
        id="coffee-demo",
        name="Coffee Machine Assistance",
        description="G1 navigates to and demonstrates assistance at the coffee machine.",
        location_id="coffee_machine",
        steps=[
            TaskStep(
                id="coffee-1",
                name="Navigate to coffee machine",
                action=ActionType.NAVIGATE,
                parameters={"location_id": "coffee_machine"},
            ),
            TaskStep(
                id="coffee-2",
                name="Detect coffee machine",
                action=ActionType.DETECT_OBJECT,
                parameters={"object_name": "coffee_machine"},
            ),
            TaskStep(
                id="coffee-3",
                name="Operate coffee machine",
                action=ActionType.MANIPULATE,
                parameters={
                    "target": "coffee_machine",
                    "operation": "operate",
                },
            ),
            TaskStep(
                id="coffee-4",
                name="Verify operation",
                action=ActionType.VERIFY,
                parameters={
                    "target": "coffee_machine",
                    "condition": "operation_complete",
                },
            ),
            TaskStep(
                id="coffee-5",
                name="Inform user",
                action=ActionType.SPEAK,
                parameters={
                    "text": "The coffee machine demonstration is complete."
                },
            ),
        ],
    ),

    Demonstration(
        id="printing-demo",
        name="3D Printing Assistance",
        description="G1 handles a completed 3D printed component.",
        location_id="3d_printer",
        steps=[
            TaskStep(
                id="print-1",
                name="Navigate to 3D printer",
                action=ActionType.NAVIGATE,
                parameters={"location_id": "3d_printer"},
            ),
            TaskStep(
                id="print-2",
                name="Detect printed part",
                action=ActionType.DETECT_OBJECT,
                parameters={"object_name": "printed_part"},
            ),
            TaskStep(
                id="print-3",
                name="Pick printed part",
                action=ActionType.PICK,
                parameters={"object_name": "printed_part"},
            ),
            TaskStep(
                id="print-4",
                name="Clean printed part",
                action=ActionType.CLEAN,
                parameters={"target": "printed_part"},
            ),
            TaskStep(
                id="print-5",
                name="Place part in box",
                action=ActionType.PLACE,
                parameters={"target": "collection_box"},
            ),
        ],
    ),

    Demonstration(
        id="cleaning-demo",
        name="Cleaning Demonstration",
        description="G1 performs a reusable cleaning task.",
        location_id="cleaning_area",
        steps=[
            TaskStep(
                id="clean-1",
                name="Navigate to cleaning area",
                action=ActionType.NAVIGATE,
                parameters={"location_id": "cleaning_area"},
            ),
            TaskStep(
                id="clean-2",
                name="Detect cleaning target",
                action=ActionType.DETECT_OBJECT,
                parameters={"object_name": "cleaning_target"},
            ),
            TaskStep(
                id="clean-3",
                name="Clean target",
                action=ActionType.CLEAN,
                parameters={"target": "cleaning_target"},
            ),
            TaskStep(
                id="clean-4",
                name="Verify cleaning",
                action=ActionType.VERIFY,
                parameters={
                    "target": "cleaning_target",
                    "condition": "cleaning_complete",
                },
            ),
        ],
    ),

    Demonstration(
        id="window-demo",
        name="Window Assistance",
        description="G1 demonstrates interaction with a window.",
        location_id="window_area",
        steps=[
            TaskStep(
                id="window-1",
                name="Navigate to window",
                action=ActionType.NAVIGATE,
                parameters={"location_id": "window_area"},
            ),
            TaskStep(
                id="window-2",
                name="Detect window handle",
                action=ActionType.DETECT_OBJECT,
                parameters={"object_name": "window_handle"},
            ),
            TaskStep(
                id="window-3",
                name="Operate window",
                action=ActionType.MANIPULATE,
                parameters={
                    "target": "window_handle",
                    "operation": "close",
                },
            ),
            TaskStep(
                id="window-4",
                name="Verify window",
                action=ActionType.VERIFY,
                parameters={
                    "target": "window",
                    "condition": "closed",
                },
            ),
        ],
    ),

    Demonstration(
        id="pick-place-demo",
        name="Pick and Place",
        description="G1 detects, picks and places an object.",
        location_id="pick_place_area",
        steps=[
            TaskStep(
                id="pick-1",
                name="Navigate to object",
                action=ActionType.NAVIGATE,
                parameters={"location_id": "pick_place_area"},
            ),
            TaskStep(
                id="pick-2",
                name="Detect object",
                action=ActionType.DETECT_OBJECT,
                parameters={"object_name": "target_object"},
            ),
            TaskStep(
                id="pick-3",
                name="Pick object",
                action=ActionType.PICK,
                parameters={"object_name": "target_object"},
            ),
            TaskStep(
                id="pick-4",
                name="Place object",
                action=ActionType.PLACE,
                parameters={"target": "destination"},
            ),
        ],
    ),
]


def get_demonstrations() -> list[Demonstration]:
    return DEMONSTRATIONS


def get_demonstration(
    demonstration_id: str,
) -> Demonstration | None:
    for demonstration in DEMONSTRATIONS:
        if demonstration.id == demonstration_id:
            return demonstration

    return None