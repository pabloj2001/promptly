"""Tasks router (02): prompt-driven create + CRUD + graph + status + comments.

Operates on the ``tasks`` collection (``task`` type). Task specs are markdown
docs too, so they support the same in-file comments as docs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import ActiveProject, get_active_project, get_claude, get_execution, get_storage
from ..models import (
    ChatHistory,
    ChatMessage,
    Comment,
    DependencyGraph,
    DocType,
    MetadataEntry,
    ProgressState,
)
from ..schemas import (
    AddCommentRequest,
    ChatRequest,
    CreateTaskRequest,
    DocOut,
    SaveBodyRequest,
    StatusChange,
    UpdateCommentRequest,
)
from ..services.claude import ClaudeService
from ..services.execution import ExecutionManager
from ..storage import ConflictError, StorageError, StorageService, ValidationError
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
    em: ExecutionManager = Depends(get_execution),
):
    """Async: create the task entry (empty body) and start its authoring execution; the
    spec is written in the background (unified executions)."""
    entry = storage.create_entry(
        ap.root, ap.name, type=DocType.task,
        display_name=req.name or provisional_name(req.prompt),
        body="", depends_on=req.depends_on, task_group=req.task_group, repo=req.repo,
    )
    await em.start_authoring(
        ap.root, ap.name, COLLECTION, entry.id, mode="generate", message=req.prompt)
    return storage.get_entry(ap.root, ap.name, COLLECTION, entry.id)


@router.post("/generate-from-spec", response_model=list[MetadataEntry], status_code=202)
async def generate_from_spec(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    claude: ClaudeService = Depends(get_claude),
    em: ExecutionManager = Depends(get_execution),
):
    """Break the project spec into tasks (03): plan -> create entries -> resolve deps ->
    author each spec in the background via its authoring execution. Returns the entries."""
    docs = storage.read_metadata(ap.root, ap.name, "docs")
    if not any(d.type == DocType.project_spec.value for d in docs.values()):
        raise ValidationError("no project spec to generate tasks from")

    stubs = await claude.plan_tasks(root=ap.root, project=ap.name)

    name_to_id: dict[str, str] = {}
    entries = []
    for stub in stubs:
        entry = storage.create_entry(
            ap.root, ap.name, type=DocType.task, display_name=stub.name,
            body="", task_group=stub.task_group,
        )
        name_to_id[stub.name] = entry.id
        entries.append(entry)

    # Resolve dependsOn (by name) and kick off each task's spec authoring.
    for stub, entry in zip(stubs, entries):
        deps = [
            name_to_id[d] for d in stub.depends_on
            if d in name_to_id and name_to_id[d] != entry.id
        ]
        if deps:
            try:
                storage.patch_metadata(ap.root, ap.name, COLLECTION, entry.id,
                                       {"dependsOn": deps})
            except ValidationError:
                deps = []  # skip dep edges that would cycle
        await em.start_authoring(
            ap.root, ap.name, COLLECTION, entry.id, mode="generate",
            message=f"{stub.name}: {stub.description}")

    return [storage.get_entry(ap.root, ap.name, COLLECTION, e.id) for e in entries]


@router.put("/{task_id}", response_model=MetadataEntry)
def save_task(
    task_id: str,
    req: SaveBodyRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.save_body(ap.root, ap.name, COLLECTION, task_id, req.body)


@router.get("/{task_id}/pr-status")
def pr_status(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    em: ExecutionManager = Depends(get_execution),
):
    """Whether the task's PR is merged (10) — the Build/Plan UI checks this before
    letting the user mark a task done."""
    entry = storage.get_entry(ap.root, ap.name, COLLECTION, task_id)
    return em.pr_status(ap.root, ap.name, entry)


@router.put("/{task_id}/status", response_model=MetadataEntry)
def set_status(
    task_id: str,
    req: StatusChange,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    em: ExecutionManager = Depends(get_execution),
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

    merged = False
    if req.status == "done":
        # Done normally follows a merged PR. If it isn't merged, warn (the client
        # confirms and retries with force); only prune the workspace once merged (10).
        status = em.pr_status(ap.root, ap.name, entry)
        merged = status["merged"]
        if not merged and not req.force:
            raise StorageError(
                "This task's PR isn't merged yet"
                if status["hasPr"] else "This task has no PR yet",
                status=409, code="pr_not_merged",
            )

    updated = storage.set_status(ap.root, ap.name, task_id, req.status)
    if req.status == "done" and merged:
        em.prune_task_workspaces(ap.root, ap.name, task_id)
    return updated


@router.post("/{task_id}/address", response_model=ProgressState)
async def address_comments(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    """Start an authoring execution (comment mode) that revises the task spec to address
    its unresolved comments directly (unified executions)."""
    return await em.start_authoring(ap.root, ap.name, COLLECTION, task_id, mode="comment")


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
    em: ExecutionManager = Depends(get_execution),
):
    storage.get_entry(ap.root, ap.name, COLLECTION, task_id)
    msg = storage.append_chat_message(ap.root, ap.name, COLLECTION, task_id, "user", req.message)
    await em.start_authoring(ap.root, ap.name, COLLECTION, task_id, mode="chat",
                            message=req.message)
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


@router.post("/{task_id}/restore", response_model=MetadataEntry)
def restore_task(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.restore_entry(ap.root, ap.name, COLLECTION, task_id)


@router.delete("/{task_id}/purge", status_code=204)
def purge_task(
    task_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    storage.purge_entry(ap.root, ap.name, COLLECTION, task_id)
