"""Slugify names into filesystem-safe filenames.

Filenames are derived from ``name`` and are never identity (the uuid ``id`` is).
Because two docs can share a name, :func:`dedupe_slug` appends ``-2``, ``-3`` ...
against a set of already-used filenames.
"""

from __future__ import annotations

import re
import unicodedata

_slug_strip = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.lower()
    value = _slug_strip.sub("-", value).strip("-")
    return value or "untitled"


def dedupe_slug(base: str, taken: set[str]) -> str:
    """Return ``base`` (a bare slug, no extension) unique against ``taken``."""
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"
