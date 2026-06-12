"""Git worktree helpers for the execution engine (07).

Each execution runs inside its own linked worktree + branch created from the root
repo's HEAD, so Claude's writes are isolated from the user's working tree until a
PR. The worktree lives at ``projects/<name>/executions/<id>/worktree`` and is
gitignored (see StorageService.ensure_gitignore).

All functions shell out to ``git``; none mutate Promptly state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


class GitError(RuntimeError):
    """A git command exited non-zero."""


def _git(args: list[str], cwd: str | Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def branch_name(task_slug: str, execution_id: str) -> str:
    """``promptly/<task-slug>-<short-id>`` (07)."""
    short = execution_id.replace("-", "")[:8]
    slug = task_slug.strip("/").strip() or "task"
    return f"promptly/{slug}-{short}"


def add_worktree(root: str, worktree: str | Path, branch: str) -> str:
    """Create ``branch`` + a linked worktree at ``worktree`` from the root HEAD.

    Returns the base commit sha the worktree was created from (used later to
    compute diffs).
    """
    base_sha = _git(["rev-parse", "HEAD"], cwd=root).strip()
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-b", branch, str(worktree), "HEAD"], cwd=root)
    return base_sha


def remove_worktree(root: str, worktree: str | Path, branch: Optional[str] = None) -> None:
    """Remove the worktree (force) and optionally delete its branch. Best-effort:
    swallows errors so cleanup never blocks the caller."""
    try:
        _git(["worktree", "remove", "--force", str(worktree)], cwd=root)
    except GitError:
        pass
    if branch:
        try:
            _git(["branch", "-D", branch], cwd=root)
        except GitError:
            pass


def head_sha(worktree: str | Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd=worktree).strip()


def has_changes(worktree: str | Path, base_sha: str) -> bool:
    out = _git(["status", "--porcelain"], cwd=worktree).strip()
    if out:
        return True
    # committed changes relative to base
    diff = _git(["diff", "--name-only", base_sha], cwd=worktree).strip()
    return bool(diff)


def commit_all(worktree: str | Path, message: str) -> Optional[str]:
    """Stage everything and commit. Returns the new sha, or None if nothing to
    commit."""
    _git(["add", "-A"], cwd=worktree)
    # Anything staged?
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=str(worktree)
    ).returncode
    if staged == 0:  # exit 0 => no staged changes
        return None
    _git(["commit", "-m", message], cwd=worktree)
    return head_sha(worktree)


def diff(worktree: str | Path, base_sha: str) -> dict:
    """Worktree (committed + uncommitted) vs. its base, for the Build Diff view (08).

    ``git diff <base_sha>`` compares the working tree against the base commit, so a
    single pass captures both committed and uncommitted changes.
    """
    name_status = _git(
        ["diff", "--name-status", base_sha], cwd=worktree
    ).strip()
    files: list[dict] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        patch = _git(["diff", base_sha, "--", path], cwd=worktree)
        files.append({"path": path, "status": status, "diff": patch})
    return {
        "baseSha": base_sha,
        "headSha": head_sha(worktree),
        "files": files,
    }


def push_branch(worktree: str | Path, branch: str) -> None:
    _git(["push", "-u", "origin", branch], cwd=worktree)
