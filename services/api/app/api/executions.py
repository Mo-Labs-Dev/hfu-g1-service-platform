
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.execution_service import execution_service


router = APIRouter(
    prefix="/api/executions",
    tags=["Execution History"],
)


@router.get("")
async def list_executions(
    workflow_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    """
    List recent workflow and demonstration executions.

    Optionally filter by workflow ID.
    """
    return await execution_service.list_executions(
        workflow_id=workflow_id,
        limit=limit,
    )


@router.get("/{execution_id}")
async def get_execution(execution_id: str):
    """
    Retrieve an execution and all its recorded steps.
    """
    execution = await execution_service.get_execution(
        execution_id,
    )

    if execution is None:
        raise HTTPException(
            status_code=404,
            detail="Execution not found.",
        )

    return execution
