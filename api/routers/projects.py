"""Projects router (02): registry list + project creation/skeleton."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from ..deps import get_storage
from ..models import DocType
from ..schemas import CreateProjectRequest, ProjectDescriptorOut
from ..storage import ConflictError, NotFoundError, StorageService, ValidationError

router = APIRouter(prefix="/projects", tags=["projects"])


def _has_project_spec(storage: StorageService, name: str, root: str) -> bool:
    docs = storage.read_metadata(root, name, "docs")
    return any(e.type == DocType.project_spec.value for e in docs.values())


@router.get("", response_model=list[ProjectDescriptorOut])
def list_projects(storage: StorageService = Depends(get_storage)):
    out = []
    for p in storage.list_projects():
        out.append(
            ProjectDescriptorOut(
                name=p.name, root=p.root, last_opened_at=p.last_opened_at,
                has_project_spec=_has_project_spec(storage, p.name, p.root),
            )
        )
    return out


@router.post("", response_model=ProjectDescriptorOut, status_code=201)
def create_project(
    req: CreateProjectRequest, storage: StorageService = Depends(get_storage)
):
    root = Path(req.root)
    if not root.exists() or not root.is_dir():
        raise ValidationError(f"root {req.root!r} does not exist")
    if not (root / ".git").exists():
        raise ValidationError(f"root {req.root!r} is not a git repository")
    if storage.get_project(req.name) is not None:
        raise ConflictError(f"project '{req.name}' already exists")
    desc = storage.create_project(req.name, str(root))
    return ProjectDescriptorOut(
        name=desc.name, root=desc.root, last_opened_at=desc.last_opened_at,
        has_project_spec=False,
    )


@router.get("/{name}", response_model=ProjectDescriptorOut)
def get_project(name: str, storage: StorageService = Depends(get_storage)):
    desc = storage.get_project(name)
    if desc is None:
        raise NotFoundError(f"project {name!r} not found")
    storage.touch_project(name)
    return ProjectDescriptorOut(
        name=desc.name, root=desc.root, last_opened_at=desc.last_opened_at,
        has_project_spec=_has_project_spec(storage, desc.name, desc.root),
    )


@router.delete("/{name}", status_code=204)
def delete_project(name: str, storage: StorageService = Depends(get_storage)):
    if storage.get_project(name) is None:
        raise NotFoundError(f"project {name!r} not found")
    storage.remove_project(name)
