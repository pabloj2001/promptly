"""Internal callbacks for execution helpers (07).

The MCP progress server (``api.mcp_server``) and the PreToolUse hook
(``api.hooks.pretooluse``) run as child processes of ``claude -p`` and report back
here. These endpoints are *not* part of the public API: they're token-guarded
(``X-Promptly-Token``) and only reachable on localhost.

Each handler mutates ``progress.json`` (the single writer is uvicorn), publishes an
SSE event on the execution bus, and — for questions / permission requests /
report-done — signals the ExecutionManager to stop the subprocess so the run loop
can pause or finalize (the kill-and-resume model).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from ..deps import (
    ActiveProject,
    get_active_project,
    get_execution,
    get_internal_token,
)
from ..models import CamelModel
from ..services.execution import ExecutionManager

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


def _auth(token: str, expected: str) -> None:
    if not expected or token != expected:
        raise HTTPException(403, detail="invalid internal token")


# ── request bodies ──────────────────────────────────────────────────────────────


class PlanStepsBody(CamelModel):
    titles: list[str]


class AddStepBody(CamelModel):
    title: str
    detail: str = ""


class UpdateStepBody(CamelModel):
    step_id: str | None = None
    title: str | None = None
    status: str | None = None
    detail: str | None = None


class AskBody(CamelModel):
    question: str


class ReportDoneBody(CamelModel):
    summary: str = ""


class PermissionRequestBody(CamelModel):
    tool: str
    request: dict = {}


# ── endpoints ───────────────────────────────────────────────────────────────────


@router.post("/executions/{execution_id}/steps/plan")
def plan_steps(
    execution_id: str,
    body: PlanStepsBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state = em.storage.plan_steps(ap.root, ap.name, execution_id, body.titles)
    em.publish_progress(execution_id, "steps", state)
    return {"ok": True}


@router.post("/executions/{execution_id}/steps/add")
def add_step(
    execution_id: str,
    body: AddStepBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state = em.storage.add_step(ap.root, ap.name, execution_id, body.title, body.detail)
    em.publish_progress(execution_id, "steps", state)
    return {"ok": True}


@router.post("/executions/{execution_id}/steps/update")
def update_step(
    execution_id: str,
    body: UpdateStepBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state = em.storage.update_step(
        ap.root, ap.name, execution_id,
        step_id=body.step_id, title=body.title, status=body.status, detail=body.detail,
    )
    em.publish_progress(execution_id, "steps", state)
    return {"ok": True}


@router.post("/executions/{execution_id}/ask")
def ask_question(
    execution_id: str,
    body: AskBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state, _ = em.storage.add_question(ap.root, ap.name, execution_id, body.question)
    em.publish_progress(execution_id, "question", state)
    em.stop(execution_id, "input")
    return {"ok": True}


@router.post("/executions/{execution_id}/permission-request")
def permission_request(
    execution_id: str,
    body: PermissionRequestBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state, _ = em.storage.add_permission_request(
        ap.root, ap.name, execution_id, body.tool, body.request
    )
    em.publish_progress(execution_id, "permission", state)
    em.stop(execution_id, "input")
    return {"ok": True}


@router.post("/executions/{execution_id}/report-done")
def report_done(
    execution_id: str,
    body: ReportDoneBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state = em.storage.set_done_summary(ap.root, ap.name, execution_id, body.summary)
    em.publish_progress(execution_id, "progress", state)
    em.stop(execution_id, "done")
    return {"ok": True}
