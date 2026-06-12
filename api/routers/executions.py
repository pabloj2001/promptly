"""Executions router (02 surface; engine in 07).

CRUD-ish endpoints (GET progress, SSE stream, diff comments) work now. The
run-loop actions (start/answer/permission/feedback/pr/diff) delegate to
ExecutionManager, which raises NotImplementedError (→ 501) until feature 07.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..deps import (
    ActiveProject,
    get_active_project,
    get_execution,
    get_storage,
)
from ..models import CommentsFile, DiffComment, ProgressState
from ..schemas import (
    AddDiffCommentRequest,
    AnswerRequest,
    FeedbackRequest,
    PermissionDecisionRequest,
    StartExecutionRequest,
    UpdateDiffCommentRequest,
)
from ..services.execution import ExecutionManager
from ..storage import StorageService

router = APIRouter(prefix="/executions", tags=["executions"])


@router.post("", response_model=ProgressState, status_code=201)
async def start_execution(
    req: StartExecutionRequest,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.start(ap.root, ap.name, req.task_id)


@router.get("/{execution_id}", response_model=ProgressState)
def get_progress(
    execution_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    prog = storage.read_progress(ap.root, ap.name, execution_id)
    if prog is None:
        raise HTTPException(404, detail=f"execution '{execution_id}' not found")
    return prog


@router.get("/{execution_id}/stream")
async def stream(
    execution_id: str,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    async def event_gen():
        async for msg in em.stream(ap.root, ap.name, execution_id):
            yield {"event": msg["event"], "data": json.dumps(msg["data"])}

    return EventSourceResponse(event_gen())


@router.post("/{execution_id}/answer", response_model=ProgressState)
async def answer(
    execution_id: str,
    req: AnswerRequest,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.answer(ap.root, ap.name, execution_id, req.question_id, req.answer)


@router.post("/{execution_id}/permission", response_model=ProgressState)
async def decide_permission(
    execution_id: str,
    req: PermissionDecisionRequest,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.decide_permission(
        ap.root, ap.name, execution_id, req.request_id, req.decision
    )


@router.post("/{execution_id}/feedback", response_model=ProgressState)
async def feedback(
    execution_id: str,
    req: FeedbackRequest,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.feedback(ap.root, ap.name, execution_id, req.message)


@router.post("/{execution_id}/pr")
async def create_pr(
    execution_id: str,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.create_pr(ap.root, ap.name, execution_id)


@router.post("/{execution_id}/cancel", response_model=ProgressState)
async def cancel(
    execution_id: str,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.cancel(ap.root, ap.name, execution_id)


@router.get("/{execution_id}/diff")
async def diff(
    execution_id: str,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    return await em.diff(ap.root, ap.name, execution_id)


@router.get("/{execution_id}/comments", response_model=CommentsFile)
def get_diff_comments(
    execution_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.read_diff_comments(ap.root, ap.name, execution_id)


@router.post("/{execution_id}/comments", response_model=DiffComment, status_code=201)
def add_diff_comment(
    execution_id: str,
    req: AddDiffCommentRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    comment = DiffComment(
        id=str(uuid.uuid4()),
        file=req.file, side=req.side,
        line_start=req.line_start, line_end=req.line_end,
        body=req.body,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return storage.add_diff_comment(ap.root, ap.name, execution_id, req.commit, comment)


@router.put("/{execution_id}/comments/{comment_id}", response_model=DiffComment)
def update_diff_comment(
    execution_id: str,
    comment_id: str,
    req: UpdateDiffCommentRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.update_diff_comment(
        ap.root, ap.name, execution_id, comment_id,
        resolved=req.resolved, body=req.body,
    )
