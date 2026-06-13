"""Internal callbacks for execution helpers (07).

The PreToolUse hook (``api.hooks.pretooluse``) runs as a child process of ``claude -p``
and reports out-of-scope write requests back here. This endpoint is *not* part of the
public API: it's token-guarded (``X-Promptly-Token``) and only reachable on localhost.

The handler mutates ``progress.json`` (the single writer is uvicorn), publishes an SSE
event, and signals the ExecutionManager to stop the subprocess so the run loop can pause
(the kill-and-resume model). Progress reporting (steps/question/issue/done) is no longer
an internal callback — it comes from the build session's ``--json-schema`` structured
output, parsed by the run loop (see api/services/exec_protocol.py).
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


class PermissionRequestBody(CamelModel):
    tool: str
    request: dict = {}


# ── endpoints ───────────────────────────────────────────────────────────────────


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
