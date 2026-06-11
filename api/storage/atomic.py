"""Atomic file writes + per-path locks.

The filesystem is our database (see 00/01), and two writers can race: the UI
saving an edit and an MCP callback updating ``progress.json`` (03/07). Every
write therefore goes through :func:`atomic_write_text`, which writes to a temp
file in the same directory and ``os.replace``s it into place (atomic on POSIX),
guarded by a per-path re-entrant lock.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# One lock per absolute path. Guarded by _locks_guard so the dict itself is safe.
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def lock_for(path: str | os.PathLike[str]) -> threading.RLock:
    key = str(Path(path).resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def atomic_write_text(path: str | os.PathLike[str], text: str) -> None:
    """Write ``text`` to ``path`` atomically, creating parent dirs as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with lock_for(p):
        tmp = p.parent / f".{p.name}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)


def write_json(path: str | os.PathLike[str], data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with lock_for(p):
        with open(p, encoding="utf-8") as f:
            text = f.read()
    if not text.strip():
        return default
    return json.loads(text)
