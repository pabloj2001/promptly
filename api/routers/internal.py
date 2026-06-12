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


class CompleteStepBody(CamelModel):
    step_id: str | None = None
    title: str | None = None


class ReviseStepsBody(CamelModel):
    steps: list[dict] = []


class AskBody(CamelModel):
    question: str


class ReportDoneBody(CamelModel):
    summary: str = ""


class PermissionRequestBody(CamelModel):
    tool: str
    request: dict = {}


# ── endpoints ───────────────────────────────────────────────────────────────────


@router.post("/executions/{execution_id}/steps/complete")
def complete_step(
    execution_id: str,
    body: CompleteStepBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state = em.storage.complete_step(
        ap.root, ap.name, execution_id, step_id=body.step_id, title=body.title)
    em.publish_progress(execution_id, "steps", state)
    return {"ok": True}


@router.post("/executions/{execution_id}/steps/revise")
def revise_steps(
    execution_id: str,
    body: ReviseStepsBody,
    x_promptly_token: str = Header(""),
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
    token: str = Depends(get_internal_token),
):
    _auth(x_promptly_token, token)
    state = em.storage.revise_steps(ap.root, ap.name, execution_id, body.steps)
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
    prog = em.storage.read_progress(ap.root, ap.name, execution_id)
    incomplete = [
        s.title for s in (prog.steps if prog else [])
        if s.status not in ("done", "skipped")
    ]
    if incomplete:
        # Don't finish: keep the session running and tell it what's left. The build
        # session must complete (or revise away) every step before reporting done.
        return {
            "ok": True,
            "complete": False,
            "message": (
                "Not done yet — these steps are still incomplete: "
                + ", ".join(incomplete)
                + ". Finish them (complete_step) or revise the plan (revise_steps), "
                "then call report_done again."
            ),
        }
    state = em.storage.set_done_summary(ap.root, ap.name, execution_id, body.summary)
    em.publish_progress(execution_id, "progress", state)
    em.stop(execution_id, "done")
    return {"ok": True, "complete": True}
