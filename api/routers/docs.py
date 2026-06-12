"""Docs router (02): prompt-driven create + CRUD + in-file comments.

Operates on the ``docs`` collection (``project_spec`` and ``doc`` types).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import (
    ActiveProject,
    get_active_project,
    get_claude,
    get_operations,
    get_storage,
)
from ..models import ChatHistory, ChatMessage, Comment, MetadataEntry
from ..schemas import (
    AddCommentRequest,
    AddressResponse,
    ChatRequest,
    CreateDocRequest,
    DocOut,
    ImportDocRequest,
    SaveBodyRequest,
    UpdateCommentRequest,
)
from ..services.claude import ClaudeService
from ..services.operations import OperationManager
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
    ops: OperationManager = Depends(get_operations),
):
    """Async: create a placeholder (operation running) and return immediately; the
    body/metadata are generated in the background (03/05)."""
    entry = storage.create_placeholder(
        ap.root, ap.name, type=req.type,
        provisional_name=req.name or provisional_name(req.prompt),
        depends_on=req.depends_on,
    )
    ops.start_generation(
        ap.root, ap.name, entry.id, COLLECTION,
        prompt=req.prompt, type=req.type, depends_on=req.depends_on, name_hint=req.name,
    )
    return entry


@router.post("/import", response_model=MetadataEntry, status_code=201)
def import_doc(
    req: ImportDocRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    """Import an existing doc verbatim (no AI). Writes the body and metadata
    synchronously."""
    return storage.create_entry(
        ap.root, ap.name, type=req.type, display_name=req.name, body=req.body,
    )


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
    ops: OperationManager = Depends(get_operations),
):
    """Append the user message + start a background chat turn (may revise the body)."""
    storage.get_entry(ap.root, ap.name, COLLECTION, doc_id)  # 404 if missing
    msg = storage.append_chat_message(ap.root, ap.name, COLLECTION, doc_id, "user", req.message)
    storage.begin_operation(ap.root, ap.name, COLLECTION, doc_id, "chat")
    ops.start_chat(ap.root, ap.name, COLLECTION, doc_id, message=req.message)
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


@router.post("/{doc_id}/address", response_model=AddressResponse)
async def address_comments(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    claude: ClaudeService = Depends(get_claude),
):
    """Generate a revision addressing unresolved comments. Returns a preview;
    the client accepts via PUT /docs/{id} (which re-anchors remaining comments)."""
    _, body, comments = storage.read_document(ap.root, ap.name, COLLECTION, doc_id)
    unresolved = [c for c in comments if not c.resolved]
    revised = await claude.address_comments(
        root=ap.root, project=ap.name, body=body, comments=unresolved,
    )
    return AddressResponse(
        revised_body=revised, addressed_comment_ids=[c.id for c in unresolved]
    )


@router.delete("/{doc_id}", response_model=MetadataEntry)
def delete_doc(
    doc_id: str,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.remove_entry(ap.root, ap.name, COLLECTION, doc_id)
