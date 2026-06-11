"""Pydantic models mirroring the on-disk schemas defined in
docs/features/01-data-model-and-storage.md.

JSON on disk uses camelCase keys (e.g. ``taskGroup``); Python attributes use
snake_case. We bridge the two with an alias generator so reads and writes are
symmetric: parse camelCase, serialize camelCase, but work in snake_case in code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model: camelCase on the wire, snake_case in code."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
    )


# ── Enums ───────────────────────────────────────────────────────────────────


class DocType(str, Enum):
    task = "task"
    project_spec = "project_spec"
    doc = "doc"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    in_review = "in_review"
    blocked = "blocked"
    done = "done"
    removed = "removed"


class ProgressStatus(str, Enum):
    running = "running"
    awaiting_input = "awaiting_input"
    completed = "completed"
    failed = "failed"


class StepStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    skipped = "skipped"


class CommentKind(str, Enum):
    comment = "comment"
    question = "question"


# ── Project registry ─────────────────────────────────────────────────────────


class ProjectDescriptor(CamelModel):
    name: str
    root: str
    last_opened_at: Optional[str] = None


# ── Document / task metadata ──────────────────────────────────────────────────


class RelatedPR(CamelModel):
    url: str
    number: int
    state: str


class MetadataEntry(CamelModel):
    id: str
    name: str
    type: DocType
    description: str = ""
    status: Optional[TaskStatus] = None
    task_group: Optional[str] = None
    related_prs: list[RelatedPR] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    custom: dict[str, Any] = Field(default_factory=dict)
    execution_id: Optional[str] = None
    file: str
    created_at: str
    updated_at: str


# ── In-file (highlight) comments ──────────────────────────────────────────────


class CommentAnchor(CamelModel):
    quote: str
    start: int
    end: int


class Comment(CamelModel):
    id: str
    anchor: CommentAnchor
    body: str
    kind: CommentKind = CommentKind.comment
    author: str = "user"
    resolved: bool = False
    orphaned: bool = False
    created_at: str


# ── Execution state ───────────────────────────────────────────────────────────


class Question(CamelModel):
    id: str
    question: str
    answer: Optional[str] = None
    asked_at: str


class PermissionRequest(CamelModel):
    id: str
    tool: str
    request: dict[str, Any] = Field(default_factory=dict)
    decision: Optional[str] = None
    asked_at: str


class Step(CamelModel):
    id: str
    title: str
    detail: str = ""
    status: StepStatus = StepStatus.pending
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class ProgressState(CamelModel):
    execution_id: str
    task_id: str
    session_id: Optional[str] = None
    status: ProgressStatus = ProgressStatus.running
    pending_questions: list[Question] = Field(default_factory=list)
    pending_permissions: list[PermissionRequest] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    created_at: str
    updated_at: str


class DiffComment(CamelModel):
    id: str
    file: str
    side: str = "new"  # "new" | "old"
    line_start: int
    line_end: int
    body: str
    author: str = "user"
    resolved: bool = False
    created_at: str


class CommentsFile(CamelModel):
    by_commit: dict[str, list[DiffComment]] = Field(default_factory=dict)


# ── Graph (Plan tab) ──────────────────────────────────────────────────────────


class GraphNode(CamelModel):
    id: str
    name: str
    status: Optional[TaskStatus] = None
    task_group: Optional[str] = None


class GraphEdge(CamelModel):
    # edge from a dependency -> the dependent task (source must finish first)
    source: str
    target: str


class DependencyGraph(CamelModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
