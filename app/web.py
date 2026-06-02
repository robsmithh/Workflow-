"""Server-rendered admin UI for managing workflows.

Renders Jinja2 templates and calls the service layer (crud/scheduler/executor)
directly rather than looping back through the JSON API. Protected by the same
shared secret as the API: when `API_KEY` is set, the user logs in once and the
key is stored in an HttpOnly cookie.
"""
from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import crud, schemas
from app.config import get_settings
from app.database import get_db
from app.models import ScheduleType
from app.scheduler import (
    get_next_run_time,
    remove_workflow_job,
    sync_workflow_job,
    trigger_now,
)

settings = get_settings()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.globals["auth_enabled"] = bool(settings.api_key)

COOKIE_NAME = "session_key"

router = APIRouter(tags=["ui"])


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def _is_authed(request: Request) -> bool:
    if not settings.api_key:
        return True  # auth disabled
    token = request.cookies.get(COOKIE_NAME)
    return bool(token) and hmac.compare_digest(token, settings.api_key)


def require_ui_auth(request: Request) -> None:
    """Dependency that redirects unauthenticated browsers to the login page."""
    if not _is_authed(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/ui/login"},
        )


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)


# --------------------------------------------------------------------------- #
# Login / logout
# --------------------------------------------------------------------------- #
@router.get("/ui/login", response_class=HTMLResponse)
def login_form(request: Request):
    if _is_authed(request):
        return _redirect("/ui")
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/ui/login")
def login_submit(request: Request, api_key: str = Form(...)):
    if not settings.api_key or not hmac.compare_digest(api_key, settings.api_key):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid API key."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    resp = _redirect("/ui")
    resp.set_cookie(
        COOKIE_NAME,
        api_key,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 12,
    )
    return resp


@router.get("/ui/logout")
def logout():
    resp = _redirect("/ui/login")
    resp.delete_cookie(COOKIE_NAME)
    return resp


# --------------------------------------------------------------------------- #
# Workflow pages
# --------------------------------------------------------------------------- #
@router.get("/ui", response_class=HTMLResponse, dependencies=[Depends(require_ui_auth)])
def dashboard(request: Request, db: Session = Depends(get_db)):
    workflows = crud.list_workflows(db, limit=500)
    rows = [
        {"wf": wf, "next_run_time": get_next_run_time(wf.id)} for wf in workflows
    ]
    return templates.TemplateResponse(
        request, "workflows_list.html", {"rows": rows}
    )


@router.get(
    "/ui/workflows/new",
    response_class=HTMLResponse,
    dependencies=[Depends(require_ui_auth)],
)
def new_workflow_form(request: Request):
    return templates.TemplateResponse(
        request,
        "workflow_form.html",
        {
            "form": _empty_form(),
            "action": "/ui/workflows",
            "title": "New workflow",
            "error": None,
            "schedule_types": list(ScheduleType),
        },
    )


@router.post("/ui/workflows", dependencies=[Depends(require_ui_auth)])
def create_workflow(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    description: str = Form(""),
    script: str = Form(...),
    schedule_type: str = Form(...),
    cron_expression: str = Form(""),
    interval_seconds: str = Form(""),
    run_at: str = Form(""),
    timeout_seconds: str = Form(""),
    enabled: str = Form("on"),
):
    try:
        payload = _form_to_create(
            name, description, script, schedule_type,
            cron_expression, interval_seconds, run_at, timeout_seconds, enabled,
        )
    except (ValidationError, ValueError) as exc:
        return _render_form_error(request, exc, locals_for_form(locals()))

    if crud.get_workflow_by_name(db, payload.name):
        return _render_form_error(
            request, "A workflow with that name already exists.",
            locals_for_form(locals()),
        )

    workflow = crud.create_workflow(db, payload)
    sync_workflow_job(workflow)
    return _redirect(f"/ui/workflows/{workflow.id}")


@router.get(
    "/ui/workflows/{workflow_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_ui_auth)],
)
def workflow_detail(workflow_id: int, request: Request, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    runs = crud.list_runs(db, workflow_id, limit=50)
    return templates.TemplateResponse(
        request,
        "workflow_detail.html",
        {
            "wf": workflow,
            "runs": runs,
            "next_run_time": get_next_run_time(workflow_id),
        },
    )


@router.get(
    "/ui/workflows/{workflow_id}/edit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_ui_auth)],
)
def edit_workflow_form(workflow_id: int, request: Request, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return templates.TemplateResponse(
        request,
        "workflow_form.html",
        {
            "form": _form_from_workflow(workflow),
            "action": f"/ui/workflows/{workflow.id}/edit",
            "title": f"Edit: {workflow.name}",
            "error": None,
            "schedule_types": list(ScheduleType),
        },
    )


@router.post("/ui/workflows/{workflow_id}/edit", dependencies=[Depends(require_ui_auth)])
def update_workflow(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    description: str = Form(""),
    script: str = Form(...),
    schedule_type: str = Form(...),
    cron_expression: str = Form(""),
    interval_seconds: str = Form(""),
    run_at: str = Form(""),
    timeout_seconds: str = Form(""),
    enabled: str = Form("off"),
):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")

    try:
        payload = _form_to_create(
            name, description, script, schedule_type,
            cron_expression, interval_seconds, run_at, timeout_seconds, enabled,
        )
    except (ValidationError, ValueError) as exc:
        return _render_form_error(
            request, exc, locals_for_form(locals()), workflow=workflow
        )

    existing = crud.get_workflow_by_name(db, payload.name)
    if existing and existing.id != workflow_id:
        return _render_form_error(
            request, "A workflow with that name already exists.",
            locals_for_form(locals()), workflow=workflow,
        )

    update = schemas.WorkflowUpdate(**payload.model_dump())
    workflow = crud.update_workflow(db, workflow, update)
    sync_workflow_job(workflow)
    return _redirect(f"/ui/workflows/{workflow.id}")


@router.post("/ui/workflows/{workflow_id}/run", dependencies=[Depends(require_ui_auth)])
def run_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    trigger_now(workflow_id, name=workflow.name)
    return _redirect(f"/ui/workflows/{workflow_id}?triggered=1")


@router.post("/ui/workflows/{workflow_id}/toggle", dependencies=[Depends(require_ui_auth)])
def toggle_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    workflow = crud.update_workflow(
        db, workflow, schemas.WorkflowUpdate(enabled=not workflow.enabled)
    )
    sync_workflow_job(workflow)
    return _redirect("/ui")


@router.post("/ui/workflows/{workflow_id}/delete", dependencies=[Depends(require_ui_auth)])
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    remove_workflow_job(workflow_id)
    crud.delete_workflow(db, workflow)
    return _redirect("/ui")


@router.get(
    "/ui/runs/{run_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_ui_auth)],
)
def run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = crud.get_run(db, run_id)
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return templates.TemplateResponse(request, "run_detail.html", {"run": run})


# --------------------------------------------------------------------------- #
# Form helpers
# --------------------------------------------------------------------------- #
def _form_to_create(
    name, description, script, schedule_type,
    cron_expression, interval_seconds, run_at, timeout_seconds, enabled,
) -> schemas.WorkflowCreate:
    return schemas.WorkflowCreate(
        name=name.strip(),
        description=description.strip() or None,
        script=script,
        schedule_type=ScheduleType(schedule_type),
        cron_expression=cron_expression.strip() or None,
        interval_seconds=int(interval_seconds) if interval_seconds.strip() else None,
        run_at=run_at.strip() or None,
        timeout_seconds=int(timeout_seconds) if timeout_seconds.strip() else None,
        enabled=enabled == "on",
    )


_FORM_KEYS = (
    "name", "description", "script", "schedule_type", "cron_expression",
    "interval_seconds", "run_at", "timeout_seconds",
)


def _empty_form() -> dict:
    return {
        "name": "", "description": "", "script": "", "schedule_type": "manual",
        "cron_expression": "", "interval_seconds": "", "run_at": "",
        "timeout_seconds": "", "enabled": True,
    }


def _form_from_workflow(wf) -> dict:
    return {
        "name": wf.name,
        "description": wf.description or "",
        "script": wf.script,
        "schedule_type": wf.schedule_type.value,
        "cron_expression": wf.cron_expression or "",
        "interval_seconds": wf.interval_seconds or "",
        "run_at": wf.run_at.strftime("%Y-%m-%dT%H:%M") if wf.run_at else "",
        "timeout_seconds": wf.timeout_seconds or "",
        "enabled": wf.enabled,
    }


def locals_for_form(local_vars: dict) -> dict:
    """Build a dict that re-populates the form on validation error."""
    data = {k: local_vars.get(k, "") for k in _FORM_KEYS}
    data["enabled"] = local_vars.get("enabled") == "on"
    return data


def _render_form_error(request, error, submitted, workflow=None):
    message = str(error)
    if isinstance(error, ValidationError):
        message = "; ".join(e["msg"] for e in error.errors())
    if workflow is not None:
        action = f"/ui/workflows/{workflow.id}/edit"
        title = f"Edit: {workflow.name}"
    else:
        action = "/ui/workflows"
        title = "New workflow"
    return templates.TemplateResponse(
        request,
        "workflow_form.html",
        {
            "form": submitted,
            "action": action,
            "title": title,
            "error": message,
            "schedule_types": list(ScheduleType),
        },
        status_code=status.HTTP_400_BAD_REQUEST,
    )
