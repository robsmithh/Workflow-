"""Workflow management and manual-trigger endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.auth import require_api_key
from app.database import get_db
from app.executor import execute_workflow_job
from app.models import TriggerType
from app.scheduler import get_next_run_time, remove_workflow_job, sync_workflow_job

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(require_api_key)],
)


def _to_out(workflow) -> schemas.WorkflowOut:
    out = schemas.WorkflowOut.model_validate(workflow)
    out.next_run_time = get_next_run_time(workflow.id)
    return out


@router.post("", response_model=schemas.WorkflowOut, status_code=status.HTTP_201_CREATED)
def create_workflow(payload: schemas.WorkflowCreate, db: Session = Depends(get_db)):
    if crud.get_workflow_by_name(db, payload.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow name already exists")
    workflow = crud.create_workflow(db, payload)
    sync_workflow_job(workflow)
    return _to_out(workflow)


@router.get("", response_model=list[schemas.WorkflowOut])
def list_workflows(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return [_to_out(w) for w in crud.list_workflows(db, skip, limit)]


@router.get("/{workflow_id}", response_model=schemas.WorkflowOut)
def get_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return _to_out(workflow)


@router.patch("/{workflow_id}", response_model=schemas.WorkflowOut)
def update_workflow(
    workflow_id: int, payload: schemas.WorkflowUpdate, db: Session = Depends(get_db)
):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    if payload.name and payload.name != workflow.name:
        existing = crud.get_workflow_by_name(db, payload.name)
        if existing and existing.id != workflow_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Workflow name already exists")
    workflow = crud.update_workflow(db, workflow, payload)
    sync_workflow_job(workflow)
    return _to_out(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    remove_workflow_job(workflow_id)
    crud.delete_workflow(db, workflow)


@router.post("/{workflow_id}/run", response_model=schemas.WorkflowRunOut)
def run_now(workflow_id: int, db: Session = Depends(get_db)):
    """Trigger an immediate, synchronous run and return the resulting run record."""
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")

    execute_workflow_job(workflow_id, trigger=TriggerType.manual.value)

    runs = crud.list_runs(db, workflow_id, limit=1)
    if not runs:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Run not recorded")
    return runs[0]


@router.get("/{workflow_id}/runs", response_model=list[schemas.WorkflowRunOut])
def list_runs(workflow_id: int, skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    if not crud.get_workflow(db, workflow_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return crud.list_runs(db, workflow_id, skip, limit)
