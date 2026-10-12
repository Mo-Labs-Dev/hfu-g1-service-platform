
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.db.models import (
    WorkflowExecution,
    WorkflowStepExecution,
)
from app.models.task import RobotTask


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def elapsed_seconds(
    start: datetime | None,
    finish: datetime,
) -> float | None:
    if start is None:
        return None

    return max(
        0.0,
        (finish - start).total_seconds(),
    )


class ExecutionService:
    async def create_execution(
        self,
        task: RobotTask,
        workflow_id: str | None = None,
        workflow_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """
        Save a pending execution before starting the task.

        The execution ID is the Task Engine's task ID.
        This allows WebSocket events and database records
        to refer to the same execution.
        """

        snapshot = workflow_snapshot or {
            "name": task.name,
            "description": task.description,
            "steps": [
                {
                    "name": step.name,
                    "action": step.action.value,
                    "parameters": step.parameters.copy(),
                }
                for step in task.steps
            ],
        }

        execution = WorkflowExecution(
            id=task.id,
            workflow_id=workflow_id,
            workflow_name=task.name,
            mode="simulation",
            status="pending",
            workflow_snapshot=snapshot,
            steps=[
                WorkflowStepExecution(
                    id=step.id,
                    position=index,
                    name=step.name,
                    action=step.action.value,
                    parameters=step.parameters.copy(),
                    status="pending",
                )
                for index, step in enumerate(task.steps)
            ],
        )

        async with AsyncSessionLocal() as session:
            session.add(execution)
            await session.commit()

    async def delete_execution(
        self,
        execution_id: str,
    ) -> None:
        """
        Remove a pending record if task scheduling fails.
        """

        async with AsyncSessionLocal() as session:
            execution = await session.get(
                WorkflowExecution,
                execution_id,
            )

            if execution is not None:
                await session.delete(execution)
                await session.commit()

    async def record_event(
        self,
        event: dict[str, Any],
    ) -> None:
        """
        Update PostgreSQL from Task Engine lifecycle events.

        Events from tasks without a registered execution
        are ignored.
        """

        event_type = event.get("type")
        data = event.get("data", {})

        if not isinstance(data, dict):
            return

        task_id = data.get("task_id")

        if not task_id:
            return

        now = utc_now()

        async with AsyncSessionLocal() as session:
            execution = await session.get(
                WorkflowExecution,
                task_id,
            )

            if execution is None:
                return

            if event_type == "task_started":
                execution.status = "running"

                if execution.started_at is None:
                    execution.started_at = now

            elif event_type == "task_completed":
                execution.status = "completed"
                execution.finished_at = now
                execution.duration_seconds = elapsed_seconds(
                    execution.started_at,
                    now,
                )

            elif event_type == "task_failed":
                execution.status = "failed"
                execution.finished_at = now
                execution.duration_seconds = elapsed_seconds(
                    execution.started_at,
                    now,
                )

                error = data.get("error")

                if error:
                    execution.error = str(error)

            elif event_type == "task_cancelled":
                execution.status = "cancelled"
                execution.finished_at = now
                execution.duration_seconds = elapsed_seconds(
                    execution.started_at,
                    now,
                )

            elif event_type in {
                "step_started",
                "step_completed",
                "step_failed",
            }:
                step_id = data.get("step_id")

                if not step_id:
                    return

                step = await session.get(
                    WorkflowStepExecution,
                    step_id,
                )

                if (
                    step is None
                    or step.execution_id != task_id
                ):
                    return

                if event_type == "step_started":
                    step.status = "running"

                    if step.started_at is None:
                        step.started_at = now

                elif event_type == "step_completed":
                    step.status = "completed"
                    step.finished_at = now
                    step.duration_seconds = elapsed_seconds(
                        step.started_at,
                        now,
                    )

                elif event_type == "step_failed":
                    step.status = "failed"
                    step.finished_at = now
                    step.duration_seconds = elapsed_seconds(
                        step.started_at,
                        now,
                    )

                    error = data.get("error")

                    if error:
                        step.error = str(error)

            else:
                return

            await session.commit()

    async def list_executions(
        self,
        workflow_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return recent execution summaries.
        """

        query = select(WorkflowExecution)

        if workflow_id is not None:
            query = query.where(
                WorkflowExecution.workflow_id == workflow_id
            )

        query = (
            query.order_by(
                WorkflowExecution.started_at.desc().nullslast(),
                WorkflowExecution.id.desc(),
            )
            .limit(max(1, min(limit, 100)))
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(query)
            executions = result.scalars().all()

            return [
                {
                    "id": execution.id,
                    "workflow_id": execution.workflow_id,
                    "workflow_name": execution.workflow_name,
                    "mode": execution.mode,
                    "status": execution.status,
                    "started_at": (
                        execution.started_at.isoformat()
                        if execution.started_at
                        else None
                    ),
                    "finished_at": (
                        execution.finished_at.isoformat()
                        if execution.finished_at
                        else None
                    ),
                    "duration_seconds": execution.duration_seconds,
                    "error": execution.error,
                }
                for execution in executions
            ]

    async def get_execution(
        self,
        execution_id: str,
    ) -> dict[str, Any] | None:
        """
        Return an execution with its step results.
        """

        async with AsyncSessionLocal() as session:
            execution = await session.get(
                WorkflowExecution,
                execution_id,
            )

            if execution is None:
                return None

            return {
                "id": execution.id,
                "workflow_id": execution.workflow_id,
                "workflow_name": execution.workflow_name,
                "mode": execution.mode,
                "status": execution.status,
                "workflow_snapshot": execution.workflow_snapshot,
                "started_at": (
                    execution.started_at.isoformat()
                    if execution.started_at
                    else None
                ),
                "finished_at": (
                    execution.finished_at.isoformat()
                    if execution.finished_at
                    else None
                ),
                "duration_seconds": execution.duration_seconds,
                "error": execution.error,
                "steps": [
                    {
                        "id": step.id,
                        "position": step.position,
                        "name": step.name,
                        "action": step.action,
                        "parameters": step.parameters,
                        "status": step.status,
                        "started_at": (
                            step.started_at.isoformat()
                            if step.started_at
                            else None
                        ),
                        "finished_at": (
                            step.finished_at.isoformat()
                            if step.finished_at
                            else None
                        ),
                        "duration_seconds": step.duration_seconds,
                        "error": step.error,
                    }
                    for step in execution.steps
                ],
            }


execution_service = ExecutionService()
