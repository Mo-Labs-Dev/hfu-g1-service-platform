import asyncio

from app.robot.mock_g1 import MockG1
from app.tasks.engine import TaskEngine
from app.models.task import RobotTask, TaskStep
from app.tasks.actions import ActionType


async def main():
    robot = MockG1()
    await robot.connect()

    engine = TaskEngine(robot)

    task = RobotTask(
        id="coffee-demo",
        name="Coffee Machine Demonstration",
        description="G1 demonstrates assistance at the coffee machine.",
        steps=[
            TaskStep(
                id="1",
                name="Navigate to coffee machine",
                action=ActionType.NAVIGATE,
                parameters={
                    "location_id": "coffee_machine"
                },
            ),
            TaskStep(
                id="2",
                name="Detect coffee machine",
                action=ActionType.DETECT_OBJECT,
                parameters={
                    "object_name": "coffee_machine"
                },
            ),
            TaskStep(
                id="3",
                name="Operate coffee machine",
                action=ActionType.MANIPULATE,
                parameters={
                    "target": "coffee_machine",
                    "operation": "operate",
                },
            ),
            TaskStep(
                id="4",
                name="Verify operation",
                action=ActionType.VERIFY,
                parameters={
                    "target": "coffee_machine",
                    "condition": "operation_complete",
                },
            ),
            TaskStep(
                id="5",
                name="Inform user",
                action=ActionType.SPEAK,
                parameters={
                    "text": "The coffee machine demonstration is complete."
                },
            ),
            TaskStep(
                id="6",
                name="Return home",
                action=ActionType.RETURN_HOME,
            ),
        ],
    )

    result = await engine.execute(task)

    print("\nFINAL STATUS:", result.status)


if __name__ == "__main__":
    asyncio.run(main())