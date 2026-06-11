"""Tasks router (02): prompt-driven create + CRUD + graph + status + comments.

Operates on the ``tasks`` collection (``task`` type). Task specs are markdown
docs too, so they support the same in-file comments as docs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import ActiveProject, get_active_project, get_claude, get_storage
from ..models import Comment, DependencyGraph, DocType, MetadataEntry
from ..schemas import (
    AddCommentRequest,
    CreateTaskRequest,
    DocOut,
    SaveBodyRequest,
    StatusChange,
    UpdateCommentRequest,
)
from ..services.claude import ClaudeService
from ..storage import ConflictError, StorageService

router = APIRouter(prefix="/tasks", tags=["tasks"])
COLLECTION = "tasks"


@router.get("", response_model=list[MetadataEntry])
def list_tasks(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return list(storage.read_metadata(ap.root, ap.name, COLLECTION).values())


@router.get("/graph", response_model=DependencyGraph)
def task_graph(
    include_removed: bool = Query(False),
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.dependency_graph(ap.root, ap.name, include_removed=include_removed)


@router.get("/{task_id}", response_model=DocOut)
def get_task(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    meta, body, comments = storage.read_document(ap.root, ap.name, COLLECTION, task_id)
    return DocOut(meta=meta, body=body, comments=comments)


@router.post("", response_model=MetadataEntry, status_code=201)
async def create_task(
    req: CreateTaskRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    claude: ClaudeService = Depends(get_claude),
):
    generated = await claude.generate_document(
        root=ap.root, project=ap.name, prompt=req.prompt, type=DocType.task,
        depends_on=req.depends_on, name_hint=req.name,
    )
    return storage.create_entry(
        ap.root, ap.name, type=DocType.task,
        display_name=req.name or generated.name,
        body=generated.body, description=generated.description,
        depends_on=req.depends_on, task_group=req.task_group,
    )


@router.put("/{task_id}", response_model=MetadataEntry)
def save_task(
    task_id: str,
    req: SaveBodyRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.save_body(ap.root, ap.name, COLLECTION, task_id, req.body)


@router.put("/{task_id}/status", response_model=MetadataEntry)
def set_status(
    task_id: str,
    req: StatusChange,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    entry = storage.get_entry(ap.root, ap.name, COLLECTION, task_id)
    # Guard: can't leave a running execution behind by jumping to done.
    # (request enum fields are coerced to plain strings by use_enum_values)
    if (
        req.status == "done"
        and entry.status in ("in_progress", "in_review")
        and entry.execution_id is not None
    ):
        prog = storage.read_progress(ap.root, ap.name, entry.execution_id)
        if prog is not None and prog.status in ("running", "awaiting_input"):
            raise ConflictError("cannot mark done while an execution is active")
    return storage.set_status(ap.root, ap.name, task_id, req.status)


@router.post("/{task_id}/comments", response_model=Comment, status_code=201)
def add_comment(
    task_id: str,
    req: AddCommentRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.add_comment(
        ap.root, ap.name, COLLECTION, task_id,
        anchor=req.anchor, body=req.body, kind=req.kind,
    )


@router.put("/{task_id}/comments/{comment_id}", response_model=Comment)
def update_comment(
    task_id: str,
    comment_id: str,
    req: UpdateCommentRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    patch = req.model_dump(by_alias=True, exclude_none=True)
    return storage.update_comment(ap.root, ap.name, COLLECTION, task_id, comment_id, patch)


@router.delete("/{task_id}", response_model=MetadataEntry)
def delete_task(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.remove_entry(ap.root, ap.name, COLLECTION, task_id)
