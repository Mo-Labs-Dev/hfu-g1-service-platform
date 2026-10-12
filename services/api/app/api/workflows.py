
from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.task import RobotTask, TaskStep
from app.models.workflow import WorkflowResponse, WorkflowWrite
from app.services.workflow_service import workflow_service
from app.tasks.engine import TaskBusyError


router = APIRouter(
    prefix="/api/workflows",
    tags=["Workflows"],
)

DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db),
]


def workflow_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Workflow not found.",
    )


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(db: DatabaseSession):
    return await workflow_service.list_workflows(db)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db: DatabaseSession,
):
    workflow = await workflow_service.get_workflow(
        db,
        workflow_id,
    )

    if workflow is None:
        raise workflow_not_found()

    return workflow


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    payload: WorkflowWrite,
    db: DatabaseSession,
):
    return await workflow_service.create_workflow(
        db,
        payload,
    )


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
)
async def update_workflow(
    workflow_id: str,
    payload: WorkflowWrite,
    db: DatabaseSession,
):
    workflow = await workflow_service.update_workflow(
        db,
        workflow_id,
        payload,
    )

    if workflow is None:
        raise workflow_not_found()

    return workflow


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workflow(
    workflow_id: str,
    db: DatabaseSession,
):
    deleted = await workflow_service.delete_workflow(
        db,
        workflow_id,
    )

    if not deleted:
        raise workflow_not_found()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    request: Request,
    db: DatabaseSession,
):
    engine = request.app.state.task_engine
    execution_service = request.app.state.execution_service

    if request.app.state.robot.mode != "simulation":
        raise HTTPException(
            status_code=503,
            detail=(
                "Custom workflow execution is enabled "
                "for MockG1 simulation only."
            ),
        )

    workflow = await workflow_service.get_workflow(
        db,
        workflow_id,
    )

    if workflow is None:
        raise workflow_not_found()

    if not workflow["steps"]:
        raise HTTPException(
            status_code=422,
            detail="Add at least one step before running.",
        )

    try:
        validated = WorkflowWrite.model_validate(workflow)

        task = RobotTask(
            id=f"workflow-{uuid4()}",
            name=validated.name,
            description=validated.description,
            steps=[
                TaskStep(
                    id=str(uuid4()),
                    name=step.name,
                    action=step.action,
                    parameters=step.parameters.copy(),
                )
                for step in validated.steps
            ],
        )

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid workflow definition: {error}",
        ) from error

    if engine.is_busy:
        raise HTTPException(
            status_code=409,
            detail="Another robot task is already running.",
        )

    # Create the persistent execution record before scheduling.
    await execution_service.create_execution(
        task=task,
        workflow_id=workflow_id,
        workflow_snapshot=workflow,
    )

    try:
        engine.start(task)

    except (TaskBusyError, ValueError) as error:
        await execution_service.delete_execution(task.id)

        raise HTTPException(
            status_code=(
                409 if isinstance(error, TaskBusyError) else 422
            ),
            detail=str(error),
        ) from error

    return {
        "accepted": True,
        "workflow_id": workflow_id,
        "task_id": task.id,
        "mode": "simulation",
        "total_steps": len(task.steps),
    }
