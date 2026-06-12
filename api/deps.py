"""Dependency wiring: service singletons + active-project resolution (02).

Active project is param-based (``?project=<name>``) — nothing hidden in server
state, multi-project comes free. The ``ActiveProject`` dependency resolves the
name to its root via the registry, 404ing if unknown.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, Query

from .services.claude import ClaudeService
from .services.execution import ExecutionManager, SSEBus
from .services.operations import OperationManager
from .storage import NotFoundError, StorageService

# Process-wide singletons.
_storage = StorageService()
_bus = SSEBus()

# Shared secret for the internal callback endpoints the execution helpers (MCP
# server, PreToolUse hook) hit. Generated per process unless pinned via env.
_internal_token = os.environ.get("PROMPTLY_TOKEN") or secrets.token_urlsafe(24)
# Where those helpers reach this server (they run on the same host).
_api_url = os.environ.get("PROMPTLY_API_URL", "http://127.0.0.1:8000")

# PROMPTLY_MODEL overrides the default model (handy for cheap smoke tests).
_claude = ClaudeService(
    _storage,
    default_model=os.environ.get("PROMPTLY_MODEL", "claude-opus-4-8"),
    internal_token=_internal_token,
    api_url=_api_url,
)
_execution = ExecutionManager(_storage, _bus, claude=_claude)
_operations = OperationManager(_storage, _claude)


def get_storage() -> StorageService:
    return _storage


def get_claude() -> ClaudeService:
    return _claude


def get_execution() -> ExecutionManager:
    return _execution


def get_operations() -> OperationManager:
    return _operations


def get_internal_token() -> str:
    return _internal_token


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
