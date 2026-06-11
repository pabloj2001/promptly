"""Storage package: the filesystem-as-database layer (01).

The public surface is :class:`StorageService`; internal modules (paths, atomic,
slug, comments, graph, registry) are implementation details.
"""

from .service import (
    ConflictError,
    NotFoundError,
    StorageError,
    StorageService,
    ValidationError,
)

__all__ = [
    "StorageService",
    "StorageError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
]
