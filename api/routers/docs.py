"""Docs router (02): prompt-driven create + CRUD + in-file comments.

Operates on the ``docs`` collection (``project_spec`` and ``doc`` types).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import (
    ActiveProject,
    get_active_project,
    get_execution,
    get_storage,
)
from ..models import (
    ChatHistory,
    ChatMessage,
    Comment,
    DocType,
    MetadataEntry,
    ProgressState,
)
from ..schemas import (
    AddCommentRequest,
    ChatRequest,
    CreateDocRequest,
    DocOut,
    ImportDocRequest,
    SaveBodyRequest,
    UpdateCommentRequest,
)
from ..services.execution import ExecutionManager
from ..storage import StorageService
from ._helpers import provisional_name

router = APIRouter(prefix="/docs", tags=["docs"])
COLLECTION = "docs"


@router.get("", response_model=list[MetadataEntry])
def list_docs(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return list(storage.read_metadata(ap.root, ap.name, COLLECTION).values())


@router.get("/{doc_id}", response_model=DocOut)
def get_doc(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    meta, body, comments = storage.read_document(ap.root, ap.name, COLLECTION, doc_id)
    return DocOut(meta=meta, body=body, comments=comments)


@router.post("", response_model=MetadataEntry, status_code=202)
async def create_doc(
    req: CreateDocRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    em: ExecutionManager = Depends(get_execution),
):
    """Async: create the entry (empty body) and start its authoring execution; the
    body/metadata are written in the background (unified executions)."""
    entry = storage.create_entry(
        ap.root, ap.name, type=req.type,
        display_name=req.name or provisional_name(req.prompt),
        body="", depends_on=req.depends_on,
    )
    collection = "tasks" if req.type == DocType.task else "docs"
    await em.start_authoring(
        ap.root, ap.name, collection, entry.id, mode="generate", message=req.prompt)
    return storage.get_entry(ap.root, ap.name, collection, entry.id)


@router.post("/import", response_model=MetadataEntry, status_code=201)
async def import_doc(
    req: ImportDocRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    em: ExecutionManager = Depends(get_execution),
):
    """Import an existing doc/task verbatim (the body is written as-is), then start an
    authoring execution in `import` mode to fill metadata — the body is never modified."""
    entry = storage.create_entry(
        ap.root, ap.name, type=req.type, display_name=req.name, body=req.body,
    )
    collection = "tasks" if req.type == DocType.task else "docs"
    await em.start_authoring(ap.root, ap.name, collection, entry.id, mode="import")
    return storage.get_entry(ap.root, ap.name, collection, entry.id)


@router.put("/{doc_id}", response_model=MetadataEntry)
def save_doc(
    doc_id: str,
    req: SaveBodyRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.save_body(ap.root, ap.name, COLLECTION, doc_id, req.body)


@router.get("/{doc_id}/chat", response_model=ChatHistory)
def get_chat(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.read_chat(ap.root, ap.name, COLLECTION, doc_id)


@router.post("/{doc_id}/chat", response_model=ChatMessage, status_code=202)
async def post_chat(
    doc_id: str,
    req: ChatRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    em: ExecutionManager = Depends(get_execution),
):
    """Append the user message + start the authoring execution in chat mode (the reply
    and any body revision arrive over the execution stream)."""
    storage.get_entry(ap.root, ap.name, COLLECTION, doc_id)  # 404 if missing
    msg = storage.append_chat_message(ap.root, ap.name, COLLECTION, doc_id, "user", req.message)
    await em.start_authoring(ap.root, ap.name, COLLECTION, doc_id, mode="chat",
                            message=req.message)
    return msg


@router.post("/{doc_id}/comments", response_model=Comment, status_code=201)
def add_comment(
    doc_id: str,
    req: AddCommentRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.add_comment(
        ap.root, ap.name, COLLECTION, doc_id,
        anchor=req.anchor, body=req.body, kind=req.kind,
    )


@router.put("/{doc_id}/comments/{comment_id}", response_model=Comment)
def update_comment(
    doc_id: str,
    comment_id: str,
    req: UpdateCommentRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    patch = req.model_dump(by_alias=True, exclude_none=True)
    return storage.update_comment(ap.root, ap.name, COLLECTION, doc_id, comment_id, patch)


@router.post("/{doc_id}/address", response_model=ProgressState)
async def address_comments(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    em: ExecutionManager = Depends(get_execution),
):
    """Start an authoring execution (comment mode) that revises the doc to address its
    unresolved comments directly. Progress + the resulting diff stream over the
    execution; comments are re-anchored when the new body is written."""
    return await em.start_authoring(ap.root, ap.name, COLLECTION, doc_id, mode="comment")


@router.delete("/{doc_id}", response_model=MetadataEntry)
def delete_doc(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.remove_entry(ap.root, ap.name, COLLECTION, doc_id)


@router.post("/{doc_id}/restore", response_model=MetadataEntry)
def restore_doc(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.restore_entry(ap.root, ap.name, COLLECTION, doc_id)


@router.delete("/{doc_id}/purge", status_code=204)
def purge_doc(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    storage.purge_entry(ap.root, ap.name, COLLECTION, doc_id)
