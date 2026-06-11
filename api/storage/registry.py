"""The app-level project registry: ``~/.promptly/projects.json``.

Lets the app list/reopen projects without scanning the disk. Lives outside any
codebase. The location is overridable via ``PROMPTLY_HOME`` (used by tests).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from ..models import ProjectDescriptor
from .atomic import read_json, write_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def promptly_home() -> Path:
    override = os.environ.get("PROMPTLY_HOME")
    return Path(override) if override else Path.home() / ".promptly"


def registry_path() -> Path:
    return promptly_home() / "projects.json"


def list_projects() -> list[ProjectDescriptor]:
    data = read_json(registry_path(), default={"projects": []}) or {"projects": []}
    return [ProjectDescriptor.model_validate(p) for p in data.get("projects", [])]


def get_project(name: str) -> ProjectDescriptor | None:
    for p in list_projects():
        if p.name == name:
            return p
    return None


def _save(projects: list[ProjectDescriptor]) -> None:
    write_json(
        registry_path(),
        {"projects": [p.model_dump(by_alias=True, exclude_none=True) for p in projects]},
    )


def upsert_project(name: str, root: str) -> ProjectDescriptor:
    projects = list_projects()
    desc = ProjectDescriptor(name=name, root=root, last_opened_at=_now())
    projects = [p for p in projects if p.name != name]
    projects.append(desc)
    _save(projects)
    return desc


def touch_project(name: str) -> None:
    """Update lastOpenedAt for an existing project."""
    projects = list_projects()
    for p in projects:
        if p.name == name:
            p.last_opened_at = _now()
    _save(projects)


def remove_project(name: str) -> None:
    _save([p for p in list_projects() if p.name != name])
