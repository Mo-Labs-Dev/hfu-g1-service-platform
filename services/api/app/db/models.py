
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Location(Base):
    __tablename__ = "locations"

    __table_args__ = (
        CheckConstraint(
            "location_type IN "
            "('home', 'navigation', 'workstation', 'interaction')",
            name="ck_locations_type",
        ),
        CheckConstraint(
            "(configured = false) OR "
            "(x IS NOT NULL AND y IS NOT NULL AND yaw IS NOT NULL)",
            name="ck_locations_configured_coordinates",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    target: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    location_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="navigation",
    )

    x: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    y: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    yaw: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    configured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "target": self.target,
            "description": self.description,
            "type": self.location_type,
            "x": self.x,
            "y": self.y,
            "yaw": self.yaw,
            "configured": self.configured,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    steps: Mapped[list[WorkflowStep]] = relationship(
        "WorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.position",
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
        }


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "position",
            name="uq_workflow_steps_position",
        ),
        CheckConstraint(
            "position >= 0",
            name="ck_workflow_steps_position",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    workflow_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "workflows.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    workflow: Mapped[Workflow] = relationship(
        "Workflow",
        back_populates="steps",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "position": self.position,
            "name": self.name,
            "action": self.action,
            "parameters": self.parameters,
        }


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    workflow_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    workflow_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="simulation",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )

    workflow_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    steps: Mapped[list[WorkflowStepExecution]] = relationship(
        "WorkflowStepExecution",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="WorkflowStepExecution.position",
        lazy="selectin",
    )


class WorkflowStepExecution(Base):
    __tablename__ = "workflow_step_executions"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    execution_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "workflow_executions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    execution: Mapped[WorkflowExecution] = relationship(
        "WorkflowExecution",
        back_populates="steps",
    )
