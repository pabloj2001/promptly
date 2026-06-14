"""Repos router (10): read/replace the per-project repo registry."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import ActiveProject, get_active_project, get_storage
from ..models import ProjectRepos
from ..storage import StorageService

router = APIRouter(tags=["repos"])


@router.get("/repos", response_model=ProjectRepos)
def get_repos(
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.read_repos(ap.root, ap.name)


@router.put("/repos", response_model=ProjectRepos)
def put_repos(
    repos: ProjectRepos,
    ap: ActiveProject = Depends(get_active_project),
    storage: StorageService = Depends(get_storage),
):
    return storage.write_repos(ap.root, ap.name, repos)
