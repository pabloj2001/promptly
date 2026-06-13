"""Settings router: read/update per-project preferences (default build instructions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ActiveProject, get_active_project, get_storage
from ..models import ProjectSettings
from ..storage import StorageService

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=ProjectSettings)
def get_settings(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.read_settings(ap.root, ap.name)


@router.put("/settings", response_model=ProjectSettings)
def put_settings(
    settings: ProjectSettings,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.write_settings(ap.root, ap.name, settings)
