"""PreToolUse approval hook for execution sessions (07/09).

Registered (via the settings we pass to ``claude -p``) to fire before every tool
call in a build session. It enforces the worktree sandbox:

- Reads (Read/Grep/Glob/…) — defer to the normal flow (allowed repo-wide).
- Write/Edit inside the worktree — allow.
- Write/Edit outside the worktree, or a Bash command not on the allow-list —
  **out of scope**: record a pending permission request in Promptly (which pauses
  the execution and routes it to the user), then deny this call. On approval the
  run loop re-spawns with the requested tool added to ``--allowedTools``.

The hook is a *thin* client: it POSTs to Promptly's localhost internal API and
prints a PreToolUse decision. State + kill/resume live in Promptly. Invoked as
``python -m api.hooks.pretooluse``; reads the hook event as JSON on stdin.

Env (set per run in the hook command we register):
  PROMPTLY_API_URL, PROMPTLY_PROJECT, PROMPTLY_EXECUTION_ID, PROMPTLY_TOKEN
  PROMPTLY_WORKTREE        abs path to this execution's worktree
  PROMPTLY_ALLOWED_BASH    JSON list of fnmatch globs for allowed Bash commands
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys

EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _decision(decision: str, reason: str) -> None:
    """Print a PreToolUse hook decision and exit."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _defer() -> None:
    """Emit nothing — let the normal permission flow handle this tool."""
    sys.exit(0)


def _in_worktree(path: str, worktree: str) -> bool:
    if not path:
        return False
    abs_path = path if os.path.isabs(path) else os.path.join(worktree, path)
    try:
        real = os.path.realpath(abs_path)
        root = os.path.realpath(worktree)
    except OSError:
        return False
    return real == root or real.startswith(root + os.sep)


def _bash_allowed(command: str, patterns: list[str]) -> bool:
    cmd = command.strip()
    return any(fnmatch.fnmatch(cmd, pat) for pat in patterns)


def _path_granted(path: str, worktree: str) -> bool:
    """True if the user already approved writing this exact path this run."""
    if not path:
        return False
    abs_path = path if os.path.isabs(path) else os.path.join(worktree, path)
    try:
        real = os.path.realpath(abs_path)
        granted = json.loads(os.environ.get("PROMPTLY_ALLOWED_PATHS", "[]"))
    except (OSError, json.JSONDecodeError):
        return False
    return real in granted


def _request_permission(tool: str, request: dict) -> None:
    """Record a pending permission request in Promptly, then deny this call.

    Best-effort: if the callback fails we still deny (fail closed) so the sandbox
    holds even when Promptly is unreachable.
    """
    api = os.environ.get("PROMPTLY_API_URL", "http://127.0.0.1:8000")
    project = os.environ.get("PROMPTLY_PROJECT", "")
    eid = os.environ.get("PROMPTLY_EXECUTION_ID", "")
    token = os.environ.get("PROMPTLY_TOKEN", "")
    try:
        import httpx

        httpx.post(
            f"{api}/internal/executions/{eid}/permission-request",
            params={"project": project},
            headers={"X-Promptly-Token": token},
            json={"tool": tool, "request": request},
            timeout=30.0,
        )
    except Exception:  # noqa: BLE001 - never let a callback error crash the hook
        pass
    _decision(
        "deny",
        f"'{tool}' is outside the execution sandbox and needs user approval. "
        "Paused for the user to decide.",
    )


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        _defer()
        return

    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}
    worktree = os.environ.get("PROMPTLY_WORKTREE", "")

    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if _in_worktree(path, worktree) or _path_granted(path, worktree):
            _decision("allow", "Edit within the worktree sandbox (or user-approved).")
        # Out of scope. "deny" = hard policy boundary; "ask" = route to the user.
        if os.environ.get("PROMPTLY_HOOK_MODE", "ask") == "deny":
            _decision(
                "deny",
                f"'{tool}' targets {path}, outside the worktree sandbox. Writes are "
                "restricted to the worktree — edit files there instead.",
            )
        _request_permission(tool, {"path": path, **_summary(tool_input)})

    if tool == "Bash":
        command = tool_input.get("command", "")
        try:
            patterns = json.loads(os.environ.get("PROMPTLY_ALLOWED_BASH", "[]"))
        except json.JSONDecodeError:
            patterns = []
        if _bash_allowed(command, patterns):
            _decision("allow", "Bash command on the allow-list.")
        _request_permission(tool, {"command": command})

    # Reads and everything else: defer to the normal (repo-wide read) flow.
    _defer()


def _summary(tool_input: dict) -> dict:
    """A small, safe excerpt of the tool input for the UI (no huge bodies)."""
    out = {}
    if "content" in tool_input:
        out["preview"] = str(tool_input["content"])[:280]
    if "new_string" in tool_input:
        out["preview"] = str(tool_input["new_string"])[:280]
    return out


if __name__ == "__main__":
    main()
