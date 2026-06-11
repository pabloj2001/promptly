"""Dependency wiring: service singletons + active-project resolution (02).

Active project is param-based (``?project=<name>``) — nothing hidden in server
state, multi-project comes free. The ``ActiveProject`` dependency resolves the
name to its root via the registry, 404ing if unknown.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Query

from .services.claude import ClaudeService
from .services.execution import ExecutionManager, SSEBus
from .storage import NotFoundError, StorageService

# Process-wide singletons.
_storage = StorageService()
_bus = SSEBus()
_claude = ClaudeService(_storage)
_execution = ExecutionManager(_storage, _bus)


def get_storage() -> StorageService:
    return _storage


def get_claude() -> ClaudeService:
    return _claude


def get_execution() -> ExecutionManager:
    return _execution


@dataclass
class ActiveProject:
    name: str
    root: str


def get_active_project(
    project: str = Query(..., description="Active project name"),
    storage: StorageService = Depends(get_storage),
) -> ActiveProject:
    desc = storage.get_project(project)
    if desc is None:
        raise NotFoundError(f"project {project!r} not found")
    return ActiveProject(name=desc.name, root=desc.root)
