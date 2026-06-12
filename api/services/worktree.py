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


def add_worktree(root: str, worktree: str | Path, branch: str, base: str = "HEAD") -> str:
    """Create ``branch`` + a linked worktree at ``worktree`` from ``base`` (a branch
    name or ref; defaults to the current HEAD).

    Returns the base commit sha the worktree was created from (used later to
    compute diffs).
    """
    base_sha = _git(["rev-parse", base], cwd=root).strip()
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-b", branch, str(worktree), base], cwd=root)
    return base_sha


# ── base-branch sync (07) ─────────────────────────────────────────────────────


def current_branch(root: str | Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).strip()


def _has_upstream(cwd: str | Path) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=str(cwd), capture_output=True, text=True,
    ).returncode == 0


def commit_paths(root: str | Path, rel_paths: list[str], message: str) -> Optional[str]:
    """Stage the given repo-relative paths and commit them (respecting .gitignore).
    Returns the new sha, or None if there was nothing to commit."""
    _git(["add", "--", *rel_paths], cwd=root)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *rel_paths], cwd=str(root)
    ).returncode
    if staged == 0:  # nothing staged
        return None
    _git(["commit", "-m", message, "--", *rel_paths], cwd=root)
    return head_sha(root)


def pull_base(root: str | Path, branch: str) -> bool:
    """Fast-forward the base branch from its upstream, if one is configured.
    Best-effort: returns True if anything was fetched/updated, False otherwise.
    Never raises on network/non-ff issues — sync degrades to local-only."""
    if not _has_upstream(root):
        return False
    try:
        before = head_sha(root)
        subprocess.run(["git", "pull", "--ff-only"], cwd=str(root),
                       capture_output=True, text=True)
        return head_sha(root) != before
    except GitError:
        return False


def push_base(root: str | Path, branch: str) -> None:
    """Push the base branch if a remote exists. Best-effort (no raise)."""
    remotes = subprocess.run(["git", "remote"], cwd=str(root),
                             capture_output=True, text=True).stdout.strip()
    if not remotes:
        return
    args = ["push"] if _has_upstream(root) else ["push", "-u", "origin", branch]
    subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)


def sync_worktree(worktree: str | Path, base_branch: str) -> dict:
    """Bring the worktree's branch up to date with ``base_branch`` (07).

    Stashes uncommitted work, merges the base in, pops the stash. Returns
    ``{"updated": bool, "conflicts": [paths]}``. Conflicts (from the merge or the
    stash pop) are left in the tree for an AI pass to resolve before resuming.
    """
    ahead = _git(["rev-list", "--count", f"HEAD..{base_branch}"], cwd=worktree).strip()
    if ahead == "0":
        return {"updated": False, "conflicts": []}

    dirty = bool(_git(["status", "--porcelain"], cwd=worktree).strip())
    if dirty:
        subprocess.run(["git", "stash", "push", "-u", "-m", "promptly-sync"],
                       cwd=str(worktree), capture_output=True, text=True)

    merge = subprocess.run(
        ["git", "merge", "--no-edit", base_branch],
        cwd=str(worktree), capture_output=True, text=True,
    )
    conflicts = _conflicted(worktree)
    if not conflicts and dirty:
        subprocess.run(["git", "stash", "pop"], cwd=str(worktree),
                       capture_output=True, text=True)
        conflicts = _conflicted(worktree)
    _ = merge  # returncode reflected by conflicts
    return {"updated": True, "conflicts": conflicts}


def _conflicted(worktree: str | Path) -> list[str]:
    out = _git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree).strip()
    return [p for p in out.splitlines() if p]


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
