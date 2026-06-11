"""Path resolution for a Promptly project.

Two locations matter (see 00):

* **the root** — the user's codebase (a git repo). Worktrees and ``.gitignore``
  live here.
* **the project dir** — ``<root>/projects/<slug(name)>/`` — all Promptly-managed
  docs, task metadata, and execution state.

This module only computes paths; it never touches the network and only creates
directories when explicitly asked (:func:`ensure_skeleton`).
"""

from __future__ import annotations

from pathlib import Path

from .slug import slugify


def project_dir(root: str, name: str) -> Path:
    return Path(root) / "projects" / slugify(name)


def project_spec_path(root: str, name: str) -> Path:
    return project_dir(root, name) / "project.md"


def permissions_path(root: str, name: str) -> Path:
    return project_dir(root, name) / "permissions.json"


def docs_dir(root: str, name: str) -> Path:
    return project_dir(root, name) / "docs"


def docs_json_path(root: str, name: str) -> Path:
    return docs_dir(root, name) / "docs.json"


def chat_path(root: str, name: str, collection: str, entry_id: str) -> Path:
    sub = "tasks" if collection == "tasks" else "docs"
    return project_dir(root, name) / sub / ".chats" / f"{entry_id}.json"


def tasks_dir(root: str, name: str) -> Path:
    return project_dir(root, name) / "tasks"


def tasks_json_path(root: str, name: str) -> Path:
    return tasks_dir(root, name) / "tasks.json"


def executions_dir(root: str, name: str) -> Path:
    return project_dir(root, name) / "executions"


def execution_dir(root: str, name: str, execution_id: str) -> Path:
    return executions_dir(root, name) / execution_id


def progress_path(root: str, name: str, execution_id: str) -> Path:
    return execution_dir(root, name, execution_id) / "progress.json"


def diff_comments_path(root: str, name: str, execution_id: str) -> Path:
    return execution_dir(root, name, execution_id) / "comments.json"


def worktree_path(root: str, name: str, execution_id: str) -> Path:
    return execution_dir(root, name, execution_id) / "worktree"


def ensure_skeleton(root: str, name: str) -> Path:
    """Create the empty project dir layout (docs/, tasks/, executions/ + empty
    metadata maps). Idempotent. Does NOT create ``project.md`` — that is the
    first Design action (05)."""
    from .atomic import read_json, write_json

    pdir = project_dir(root, name)
    docs_dir(root, name).mkdir(parents=True, exist_ok=True)
    tasks_dir(root, name).mkdir(parents=True, exist_ok=True)
    executions_dir(root, name).mkdir(parents=True, exist_ok=True)

    dj = docs_json_path(root, name)
    if read_json(dj) is None:
        write_json(dj, {})
    tj = tasks_json_path(root, name)
    if read_json(tj) is None:
        write_json(tj, {})
    return pdir
