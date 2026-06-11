"""Metadata router (02): patch any metadata field, incl. the custom kv map.

Used by the Design metadata panel and the Plan side panel for both docs and tasks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ActiveProject, get_active_project, get_storage
from ..models import MetadataEntry
from ..schemas import MetadataPatch
from ..storage import StorageService

router = APIRouter(tags=["metadata"])


def _patch(storage, ap, collection, entry_id, req: MetadataPatch) -> MetadataEntry:
    patch = req.model_dump(by_alias=True, exclude_none=True)
    return storage.patch_metadata(ap.root, ap.name, collection, entry_id, patch)


@router.put("/docs/{doc_id}/metadata", response_model=MetadataEntry)
def patch_doc_metadata(
    doc_id: str,
    req: MetadataPatch,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return _patch(storage, ap, "docs", doc_id, req)


@router.put("/tasks/{task_id}/metadata", response_model=MetadataEntry)
def patch_task_metadata(
    task_id: str,
    req: MetadataPatch,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return _patch(storage, ap, "tasks", task_id, req)
