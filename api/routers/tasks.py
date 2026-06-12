"""Tasks router (02): prompt-driven create + CRUD + graph + status + comments.

Operates on the ``tasks`` collection (``task`` type). Task specs are markdown
docs too, so they support the same in-file comments as docs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import ActiveProject, get_active_project, get_claude, get_storage
from ..models import ChatHistory, ChatMessage, Comment, DependencyGraph, DocType, MetadataEntry
from ..schemas import (
    AddCommentRequest,
    AddressResponse,
    ChatRequest,
    CreateTaskRequest,
    DocOut,
    SaveBodyRequest,
    StatusChange,
    UpdateCommentRequest,
)
from ..deps import get_claude, get_operations
from ..services.claude import ClaudeService
from ..services.operations import OperationManager
from ..storage import ConflictError, StorageService, ValidationError
from ._helpers import provisional_name

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


@router.post("", response_model=MetadataEntry, status_code=202)
async def create_task(
    req: CreateTaskRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    ops: OperationManager = Depends(get_operations),
):
    """Async: placeholder now, task spec generated in the background (03/05)."""
    entry = storage.create_placeholder(
        ap.root, ap.name, type=DocType.task,
        provisional_name=req.name or provisional_name(req.prompt),
        depends_on=req.depends_on, task_group=req.task_group,
    )
    ops.start_generation(
        ap.root, ap.name, entry.id, COLLECTION,
        prompt=req.prompt, type=DocType.task, depends_on=req.depends_on, name_hint=req.name,
    )
    return entry


@router.post("/generate-from-spec", response_model=list[MetadataEntry], status_code=202)
async def generate_from_spec(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    claude: ClaudeService = Depends(get_claude),
    ops: OperationManager = Depends(get_operations),
):
    """Break the project spec into tasks (03): plan -> create placeholders ->
    resolve deps -> generate each body in the background. Returns placeholders."""
    docs = storage.read_metadata(ap.root, ap.name, "docs")
    if not any(d.type == DocType.project_spec.value for d in docs.values()):
        raise ValidationError("no project spec to generate tasks from")

    stubs = await claude.plan_tasks(root=ap.root, project=ap.name)

    name_to_id: dict[str, str] = {}
    placeholders = []
    for stub in stubs:
        ph = storage.create_placeholder(
            ap.root, ap.name, type=DocType.task,
            provisional_name=stub.name, task_group=stub.task_group,
        )
        name_to_id[stub.name] = ph.id
        placeholders.append(ph)

    # Resolve dependsOn (by name) and kick off each task's body generation.
    for stub, ph in zip(stubs, placeholders):
        deps = [
            name_to_id[d] for d in stub.depends_on
            if d in name_to_id and name_to_id[d] != ph.id
        ]
        if deps:
            try:
                storage.patch_metadata(ap.root, ap.name, COLLECTION, ph.id,
                                       {"dependsOn": deps})
            except ValidationError:
                deps = []  # skip dep edges that would cycle
        ops.start_generation(
            ap.root, ap.name, ph.id, COLLECTION,
            prompt=f"{stub.name}: {stub.description}",
            type=DocType.task, depends_on=deps, name_hint=stub.name,
        )

    return placeholders


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


@router.post("/{task_id}/address", response_model=AddressResponse)
async def address_comments(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    claude: ClaudeService = Depends(get_claude),
):
    _, body, comments = storage.read_document(ap.root, ap.name, COLLECTION, task_id)
    unresolved = [c for c in comments if not c.resolved]
    revised = await claude.address_comments(
        root=ap.root, project=ap.name, body=body, comments=unresolved,
    )
    return AddressResponse(
        revised_body=revised, addressed_comment_ids=[c.id for c in unresolved]
    )


@router.get("/{task_id}/chat", response_model=ChatHistory)
def get_chat(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.read_chat(ap.root, ap.name, COLLECTION, task_id)


@router.post("/{task_id}/chat", response_model=ChatMessage, status_code=202)
async def post_chat(
    task_id: str,
    req: ChatRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    ops: OperationManager = Depends(get_operations),
):
    storage.get_entry(ap.root, ap.name, COLLECTION, task_id)
    msg = storage.append_chat_message(ap.root, ap.name, COLLECTION, task_id, "user", req.message)
    storage.begin_operation(ap.root, ap.name, COLLECTION, task_id, "chat")
    ops.start_chat(ap.root, ap.name, COLLECTION, task_id, message=req.message)
    return msg


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
