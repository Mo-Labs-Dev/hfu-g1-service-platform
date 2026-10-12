from app.data.demonstrations import (
    get_demonstration,
    get_demonstrations,
)
from app.models.demonstration import Demonstration
from app.models.task import RobotTask
from app.tasks.engine import TaskEngine


class DemonstrationService:

    def __init__(self, task_engine: TaskEngine):
        self.task_engine = task_engine

    def list_demonstrations(self) -> list[Demonstration]:
        return get_demonstrations()

    def find_demonstration(
        self,
        demonstration_id: str,
    ) -> Demonstration | None:
        return get_demonstration(demonstration_id)

    async def run_demonstration(
        self,
        demonstration_id: str,
    ) -> RobotTask:

        demonstration = self.find_demonstration(
            demonstration_id
        )

        if demonstration is None:
            raise ValueError(
                f"Demonstration '{demonstration_id}' not found"
            )

        task = RobotTask(
            id=f"task-{demonstration.id}",
            name=demonstration.name,
            description=demonstration.description,
            steps=[
                step.model_copy(deep=True)
                for step in demonstration.steps
            ],
        )

        return await self.task_engine.execute(task)