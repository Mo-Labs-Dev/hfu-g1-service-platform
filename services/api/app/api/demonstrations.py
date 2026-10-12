
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.models.demonstration import Demonstration
from app.models.task import RobotTask
from app.tasks.engine import TaskBusyError


router = APIRouter(
    prefix="/api/demonstrations",
    tags=["Demonstrations"],
)


@router.get("", response_model=list[Demonstration])
async def list_demonstrations(request: Request):
    service = request.app.state.demonstration_service
    return service.list_demonstrations()


@router.get(
    "/{demonstration_id}",
    response_model=Demonstration,
)
async def get_demonstration(
    demonstration_id: str,
    request: Request,
):
    service = request.app.state.demonstration_service

    demonstration = service.find_demonstration(
        demonstration_id
    )

    if demonstration is None:
        raise HTTPException(
            status_code=404,
            detail="Demonstration not found",
        )

    return demonstration


@router.post("/{demonstration_id}/run")
async def run_demonstration(
    demonstration_id: str,
    request: Request,
):
    service = request.app.state.demonstration_service

    demonstration = service.find_demonstration(
        demonstration_id
    )

    if demonstration is None:
        raise HTTPException(
            status_code=404,
            detail="Demonstration not found",
        )

    task = RobotTask(
        id=f"demo-{uuid4()}",
        name=demonstration.name,
        description=demonstration.description,
        steps=[
            step.model_copy(deep=True)
            for step in demonstration.steps
        ],
    )

    try:
        service.task_engine.start(task)

    except TaskBusyError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    return {
        "accepted": True,
        "demonstration_id": demonstration_id,
        "task_id": task.id,
        "mode": "simulation",
    }
