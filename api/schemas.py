"""HTTP request/response schemas for the API (02).

These are the wire contracts for the routers; they sit on top of the on-disk
models in :mod:`api.models`. camelCase on the wire, snake_case in code.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from .models import (
    CamelModel,
    Comment,
    CommentKind,
    DocType,
    MetadataEntry,
    TaskStatus,
)


# ── Projects ──────────────────────────────────────────────────────────────────


class CreateProjectRequest(CamelModel):
    name: str
    root: str


class ProjectDescriptorOut(CamelModel):
    name: str
    root: str
    last_opened_at: Optional[str] = None
    has_project_spec: bool = False


# ── Docs / tasks ───────────────────────────────────────────────────────────────


class CreateDocRequest(CamelModel):
    prompt: str
    type: DocType = DocType.doc
    name: Optional[str] = None
    depends_on: list[str] = Field(default_factory=list)


class CreateTaskRequest(CamelModel):
    prompt: str
    name: Optional[str] = None
    depends_on: list[str] = Field(default_factory=list)
    task_group: Optional[str] = None


class DocOut(CamelModel):
    """Metadata + parsed body + parsed comments."""

    meta: MetadataEntry
    body: str
    comments: list[Comment] = Field(default_factory=list)


class SaveBodyRequest(CamelModel):
    body: str


class AddCommentRequest(CamelModel):
    anchor: dict[str, Any]
    body: str
    kind: CommentKind = CommentKind.comment


class UpdateCommentRequest(CamelModel):
    body: Optional[str] = None
    resolved: Optional[bool] = None


class AddressResponse(CamelModel):
    """Proposed revision returned for preview (not yet written)."""

    revised_body: str
    addressed_comment_ids: list[str] = Field(default_factory=list)


class MetadataPatch(CamelModel):
    name: Optional[str] = None
    description: Optional[str] = None
    task_group: Optional[str] = None
    depends_on: Optional[list[str]] = None
    custom: Optional[dict[str, Any]] = None


class StatusChange(CamelModel):
    status: TaskStatus


# ── Executions ─────────────────────────────────────────────────────────────────


class StartExecutionRequest(CamelModel):
    task_id: str


class AnswerRequest(CamelModel):
    question_id: str
    answer: str


class PermissionDecisionRequest(CamelModel):
    request_id: str
    decision: str  # "allow" | "deny"


class FeedbackRequest(CamelModel):
    message: str


class AddDiffCommentRequest(CamelModel):
    commit: str
    file: str
    side: str = "new"
    line_start: int
    line_end: int
    body: str
