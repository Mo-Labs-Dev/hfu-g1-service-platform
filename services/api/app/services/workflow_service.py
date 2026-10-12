
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workflow, WorkflowStep
from app.models.workflow import WorkflowWrite


class WorkflowService:
    async def list_workflows(
        self,
        db: AsyncSession,
    ) -> list[dict]:
        result = await db.execute(
            select(Workflow).order_by(
                Workflow.created_at.desc()
            )
        )

        workflows = result.scalars().all()

        return [
            workflow.to_dict()
            for workflow in workflows
        ]

    async def get_workflow(
        self,
        db: AsyncSession,
        workflow_id: str,
    ) -> dict | None:
        workflow = await db.get(
            Workflow,
            workflow_id,
        )

        if workflow is None:
            return None

        return workflow.to_dict()

    async def create_workflow(
        self,
        db: AsyncSession,
        payload: WorkflowWrite,
    ) -> dict:
        workflow = Workflow(
            id=str(uuid4()),
            name=payload.name.strip(),
            description=payload.description.strip(),
            status=payload.status,
        )

        workflow.steps = self._build_steps(payload)

        db.add(workflow)

        await db.commit()

        return await self.get_workflow(
            db,
            workflow.id,
        )

    async def update_workflow(
        self,
        db: AsyncSession,
        workflow_id: str,
        payload: WorkflowWrite,
    ) -> dict | None:
        workflow = await db.get(
            Workflow,
            workflow_id,
        )

        if workflow is None:
            return None

        workflow.name = payload.name.strip()
        workflow.description = payload.description.strip()
        workflow.status = payload.status

        workflow.steps.clear()
        await db.flush()

        workflow.steps = self._build_steps(payload)

        await db.commit()

        return await self.get_workflow(
            db,
            workflow_id,
        )

    async def delete_workflow(
        self,
        db: AsyncSession,
        workflow_id: str,
    ) -> bool:
        workflow = await db.get(
            Workflow,
            workflow_id,
        )

        if workflow is None:
            return False

        await db.delete(workflow)
        await db.commit()

        return True

    @staticmethod
    def _build_steps(
        payload: WorkflowWrite,
    ) -> list[WorkflowStep]:
        return [
            WorkflowStep(
                id=str(uuid4()),
                position=index,
                name=step.name.strip(),
                action=step.action.value,
                parameters=step.parameters,
            )
            for index, step in enumerate(payload.steps)
        ]


workflow_service = WorkflowService()
