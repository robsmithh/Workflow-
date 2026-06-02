"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import RunStatus, ScheduleType, TriggerType


class WorkflowBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    script: str = Field(..., min_length=1)
    schedule_type: ScheduleType = ScheduleType.manual
    cron_expression: str | None = None
    interval_seconds: int | None = Field(default=None, gt=0)
    run_at: datetime | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_schedule_fields(self) -> "WorkflowBase":
        if self.schedule_type == ScheduleType.cron and not self.cron_expression:
            raise ValueError("cron_expression is required when schedule_type=cron")
        if self.schedule_type == ScheduleType.interval and not self.interval_seconds:
            raise ValueError("interval_seconds is required when schedule_type=interval")
        if self.schedule_type == ScheduleType.date and not self.run_at:
            raise ValueError("run_at is required when schedule_type=date")
        return self


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowUpdate(BaseModel):
    """All fields optional; only provided fields are updated."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    script: str | None = Field(default=None, min_length=1)
    schedule_type: ScheduleType | None = None
    cron_expression: str | None = None
    interval_seconds: int | None = Field(default=None, gt=0)
    run_at: datetime | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


class WorkflowOut(WorkflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    next_run_time: datetime | None = None


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    status: RunStatus
    trigger: TriggerType
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    created_at: datetime
