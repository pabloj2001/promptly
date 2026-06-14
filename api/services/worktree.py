"""Git worktree helpers for the execution engine (07).

Each execution runs inside its own linked worktree + branch created from the root
repo's HEAD, so Claude's writes are isolated from the user's working tree until a
PR. The worktree lives at ``projects/<name>/executions/<id>/worktree`` and is
gitignored (see StorageService.ensure_gitignore).

All functions shell out to ``git``; none mutate Promptly state.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Directories never worth scanning for nested repos / diffs (deps, build output).
_PRUNE_DIRS = {"node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".next"}


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


def add_worktree_detached(root: str, worktree: str | Path, commitish: str = "HEAD") -> str:
    """Create a **detached** (branchless) linked worktree at ``worktree`` — used for
    read-only context checkouts of the primary repo in a multi-repo workspace (10).
    Returns the checked-out commit sha."""
    sha = _git(["rev-parse", commitish], cwd=root).strip()
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "--detach", str(worktree), commitish], cwd=root)
    return sha


def ensure_mirror(cache: str | Path, url: str) -> None:
    """Ensure a bare mirror of ``url`` at ``cache`` and bring it up to date (10). The
    mirror is fetched once and refreshed; workspace clones borrow its objects so each
    execution's clone is tiny."""
    cache = Path(cache)
    if (cache / "HEAD").exists():
        subprocess.run(["git", "remote", "update", "--prune"],
                       cwd=str(cache), capture_output=True, text=True)
        return
    cache.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "--mirror", url, str(cache)], cwd=cache.parent)


def clone_from_mirror(
    cache: str | Path, dest: str | Path, url: str, *,
    branch: Optional[str] = None, base_branch: Optional[str] = None,
) -> str:
    """Clone a working checkout at ``dest`` that **shares objects** with the bare mirror
    ``cache`` (``git clone --shared``), then point ``origin`` at the real ``url`` so
    push/PR target the real remote (10). Optionally check out ``base_branch`` and create
    a new ``branch``. Returns the base commit sha."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    args = ["clone", "--shared"]
    if base_branch:
        args += ["--branch", base_branch]
    args += [str(cache), str(dest)]
    _git(args, cwd=Path(dest).parent)
    _git(["remote", "set-url", "origin", url], cwd=dest)
    base_sha = head_sha(dest)
    if branch:
        _git(["checkout", "-b", branch], cwd=dest)
    return base_sha


def remove_workspace(root: str, workspace: str | Path) -> None:
    """Tear down an execution workspace (10): remove any linked worktrees (primary
    checkouts) then delete the whole tree (clones are plain dirs). Best-effort."""
    ws = Path(workspace)
    if not ws.exists():
        return
    for sub in ws.iterdir():
        if sub.is_dir():
            subprocess.run(["git", "worktree", "remove", "--force", str(sub)],
                           cwd=str(root), capture_output=True, text=True)
    shutil.rmtree(ws, ignore_errors=True)
    subprocess.run(["git", "worktree", "prune"], cwd=str(root),
                   capture_output=True, text=True)


def clone_repo(
    url: str, dest: str | Path, *, branch: Optional[str] = None,
    base_branch: Optional[str] = None,
) -> str:
    """Clone ``url`` into ``dest`` (10). Optionally start from ``base_branch`` and create
    a new working ``branch``. Returns the base commit sha (the clone's HEAD before any
    new branch)."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    args = ["clone"]
    if base_branch:
        args += ["--branch", base_branch]
    args += [url, str(dest)]
    _git(args, cwd=Path(dest).parent)
    base_sha = head_sha(dest)
    if branch:
        _git(["checkout", "-b", branch], cwd=dest)
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


def branch_exists(root: str | Path, branch: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(root), capture_output=True, text=True,
    ).returncode == 0


def merge_branches(worktree: str | Path, branches: list[str]) -> dict:
    """Merge each branch into the (freshly created, clean) worktree in order, so the
    worktree builds on top of those branches' work. Stops at the first merge that
    produces conflicts, leaving the markers for an AI pass to resolve before the run.

    Returns ``{"merged": [branches merged cleanly], "conflicts": [paths]}``.
    """
    merged: list[str] = []
    for b in branches:
        subprocess.run(["git", "merge", "--no-edit", b],
                       cwd=str(worktree), capture_output=True, text=True)
        conflicts = _conflicted(worktree)
        if conflicts:
            return {"merged": merged, "conflicts": conflicts}
        merged.append(b)
    return {"merged": merged, "conflicts": []}


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


def _run_git(args: list[str], cwd: str | Path) -> str:
    """Like _git but tolerant: returns stdout and never raises (some diff commands
    exit non-zero by design, e.g. `diff --no-index`, or on a repo with no commits)."""
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True).stdout


def find_nested_repos(worktree: str | Path) -> list[Path]:
    """Git repositories that live *inside* the worktree (the user's actual code may be
    in nested repos rather than tracked by the outer worktree). Returns their dirs;
    does not descend into a repo once found, and prunes dependency/build dirs."""
    wt = Path(worktree)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(wt):
        here = Path(dirpath)
        # A ".git" dir (normal clone) or file (submodule/linked worktree) marks a repo.
        if here != wt and (".git" in dirnames or ".git" in filenames):
            found.append(here)
            dirnames[:] = []  # don't descend into a nested repo
            continue
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS and d != ".git"]
    return found


def _collect_changes(
    repo: str | Path, base: str, *, prefix: str = "", skip: Optional[set[str]] = None,
) -> list[dict]:
    """File changes in ``repo`` vs ``base``: tracked (committed + uncommitted) plus
    untracked new files. ``prefix`` is prepended to each path (for nested repos);
    ``skip`` is a set of repo-relative dir paths to omit (nested repos handled
    separately)."""
    skip = skip or set()
    files: list[dict] = []

    def skipped(path: str) -> bool:
        return any(path == s or path.startswith(s + "/") for s in skip)

    # Tracked changes vs base.
    name_status = _run_git(["diff", "--name-status", base], cwd=repo).strip()
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if skipped(path):
            continue
        patch = _run_git(["diff", base, "--", path], cwd=repo)
        files.append({"path": prefix + path, "status": status, "diff": patch})

    # Untracked new files (not shown by `git diff <base>`).
    others = _run_git(
        ["ls-files", "--others", "--exclude-standard"], cwd=repo).strip()
    for path in others.splitlines():
        path = path.rstrip("/")
        if not path or skipped(path):
            continue
        patch = _run_git(["diff", "--no-index", "--", os.devnull, path], cwd=repo)
        files.append({"path": prefix + path, "status": "A", "diff": patch})

    return files


def diff(worktree: str | Path, base_sha: str) -> dict:
    """All changes for the Build Diff view (08): the worktree vs its base, **plus** any
    nested git repos inside the worktree (the user's code may live in them). For the
    outer worktree we diff against ``base_sha`` (committed + uncommitted + untracked);
    for each nested repo we diff its working tree vs its own HEAD (the build session
    doesn't commit), with paths prefixed by the repo's location."""
    wt = Path(worktree)
    nested = find_nested_repos(wt)
    nested_rel = {str(r.relative_to(wt)).replace(os.sep, "/") for r in nested}

    files = _collect_changes(wt, base_sha, skip=nested_rel)
    for repo in nested:
        prefix = str(repo.relative_to(wt)).replace(os.sep, "/") + "/"
        files.extend(_collect_changes(repo, "HEAD", prefix=prefix))

    return {
        "baseSha": base_sha,
        "headSha": head_sha(wt),
        "files": files,
    }


def push_branch(worktree: str | Path, branch: str) -> None:
    _git(["push", "-u", "origin", branch], cwd=worktree)
