"""Permissions router (02/09): read/update the per-project permissions config."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ActiveProject, get_active_project, get_storage
from ..models import PermissionsConfig
from ..storage import StorageService

router = APIRouter(tags=["permissions"])


@router.get("/permissions", response_model=PermissionsConfig)
def get_permissions(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.read_permissions(ap.root, ap.name)


@router.put("/permissions", response_model=PermissionsConfig)
def put_permissions(
    config: PermissionsConfig,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.write_permissions(ap.root, ap.name, config)
