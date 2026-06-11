"""Docs router (02): prompt-driven create + CRUD + in-file comments.

Operates on the ``docs`` collection (``project_spec`` and ``doc`` types).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ActiveProject, get_active_project, get_claude, get_storage
from ..models import Comment, MetadataEntry
from ..schemas import (
    AddCommentRequest,
    AddressResponse,
    CreateDocRequest,
    DocOut,
    SaveBodyRequest,
    UpdateCommentRequest,
)
from ..services.claude import ClaudeService
from ..storage import StorageService

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


@router.post("", response_model=MetadataEntry, status_code=201)
async def create_doc(
    req: CreateDocRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
    claude: ClaudeService = Depends(get_claude),
):
    generated = await claude.generate_document(
        root=ap.root, project=ap.name, prompt=req.prompt, type=req.type,
        depends_on=req.depends_on, name_hint=req.name,
    )
    return storage.create_entry(
        ap.root, ap.name, type=req.type,
        display_name=req.name or generated.name,
        body=generated.body, description=generated.description,
        depends_on=req.depends_on,
    )


@router.put("/{doc_id}", response_model=MetadataEntry)
def save_doc(
    doc_id: str,
    req: SaveBodyRequest,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.save_body(ap.root, ap.name, COLLECTION, doc_id, req.body)


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
