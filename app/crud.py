"""Database access helpers for workflows and runs."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.models import Workflow, WorkflowRun


def create_workflow(db: Session, data: schemas.WorkflowCreate) -> Workflow:
    workflow = Workflow(**data.model_dump())
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow(db: Session, workflow_id: int) -> Workflow | None:
    return db.get(Workflow, workflow_id)


def get_workflow_by_name(db: Session, name: str) -> Workflow | None:
    return db.scalar(select(Workflow).where(Workflow.name == name))


def list_workflows(db: Session, skip: int = 0, limit: int = 100) -> list[Workflow]:
    stmt = select(Workflow).order_by(Workflow.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_workflow(
    db: Session, workflow: Workflow, data: schemas.WorkflowUpdate
) -> Workflow:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(workflow, field, value)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def delete_workflow(db: Session, workflow: Workflow) -> None:
    db.delete(workflow)
    db.commit()


def list_runs(
    db: Session, workflow_id: int, skip: int = 0, limit: int = 50
) -> list[WorkflowRun]:
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id)
        .order_by(WorkflowRun.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_run(db: Session, run_id: int) -> WorkflowRun | None:
    return db.get(WorkflowRun, run_id)
