"""JSON structured-output protocol for build sessions (07).

Instead of an MCP server, the build session reports progress by returning ONE
schema-validated command per ``claude -p`` turn (via ``--json-schema``). The command
lands in the final ``result`` event's ``structured_output`` (parsed live), and is also
recorded in the session transcript as a ``tool_use`` block named ``StructuredOutput`` —
which we read as a fallback when a turn's process is lost (e.g. server restart).

Command shapes (``type`` required):
  {"type":"thinking","text":...}                      progress note (surfaced, optional)
  {"type":"step_complete","step":N}                   mark step number N done
  {"type":"revise_steps","steps":[{title,detail?,done}]}  replace the whole plan
  {"type":"question","question":...}                  ask the user (pauses)
  {"type":"issue","issue":...,"detail"?:...}          report a blocker (pauses)
  {"type":"done","summary":...}                       task complete
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

COMMAND_TYPES = ["thinking", "step_complete", "revise_steps", "question", "issue", "done"]

# Passed to ``claude --json-schema``. ``type`` is required; the rest are optional and
# validated per-type in code (the live test confirmed this permissive shape works).
COMMAND_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": COMMAND_TYPES},
        "step": {"type": "integer"},
        "title": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "done": {"type": "boolean"},
                },
                "required": ["title"],
            },
        },
        "question": {"type": "string"},
        "issue": {"type": "string"},
        "detail": {"type": "string"},
        "summary": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["type"],
}

# Doc-authoring turn schema (unified executions): a much smaller command set than the
# build loop. The model researches within a turn (Read/Grep) then returns either a
# ``question`` (pause for the user) or ``done`` with the full updated body (and, for
# chat, a short ``reply``). ``thinking`` is an optional surfaced progress note.
# All three types are a subset of COMMAND_TYPES, so command_from_result_event /
# read_transcript_command parse doc commands unchanged.
DOC_COMMAND_TYPES = ["thinking", "question", "done"]
DOC_COMMAND_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": DOC_COMMAND_TYPES},
        "question": {"type": "string"},
        "body": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "reply": {"type": "string"},
        "summary": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["type"],
}

# Schema for the planning phase (07): a one-shot call that returns the ordered step list.
PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    "required": ["steps"],
}

# The CLI surfaces structured output as a synthetic tool with this name.
_STRUCTURED_TOOL = "StructuredOutput"


def is_command(obj: Any) -> bool:
    return isinstance(obj, dict) and obj.get("type") in COMMAND_TYPES


def command_from_result_event(event: dict) -> Optional[dict]:
    """Pull the command from a stream-json ``result`` event's ``structured_output``."""
    so = event.get("structured_output")
    return so if is_command(so) else None


def assistant_texts(event_or_entry: dict) -> list[str]:
    """Text blocks from a stream-json assistant event or a transcript assistant entry
    (same ``message.content`` shape) — used for the compact live activity line."""
    content = (event_or_entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
            out.append(b["text"])
    return out


# Tool name → human verb, so the activity line reads like a sentence
# ("Editing service.py") instead of an API name ("Edit: api/storage/service.py").
_TOOL_VERBS = {
    "Edit": "Editing",
    "MultiEdit": "Editing",
    "Write": "Writing",
    "Read": "Reading",
    "NotebookEdit": "Editing",
    "Bash": "Running",
    "Grep": "Searching for",
    "Glob": "Finding",
    "WebFetch": "Fetching",
    "WebSearch": "Searching for",
    "Task": "Delegating",
    "TodoWrite": "Updating plan",
}

# Leading `FOO=bar BAZ='x y'` assignments on a shell command — noise we strip so the
# activity shows the actual command ("python3 -m pytest", not "PYTHONPATH=. python3 …").
_ENV_PREFIX = re.compile(r"^(?:\w+=(?:'[^']*'|\"[^\"]*\"|\S+)\s+)+")


def _tool_activity(name: str, inp: dict) -> str:
    """One readable phrase for a tool_use: a verb plus a short, de-noised target
    (basenames for files, the env-stripped command for Bash, the query for searches)."""
    verb = _TOOL_VERBS.get(name, name)
    if name == "Bash":
        cmd = str(inp.get("command") or "").strip()
        cmd = cmd.splitlines()[0] if cmd else ""
        cmd = _ENV_PREFIX.sub("", cmd).strip()
        return f"{verb} {cmd}".strip() if cmd else verb
    if name in ("Grep", "Glob", "WebSearch"):
        q = str(inp.get("pattern") or inp.get("query") or "").strip()
        return f"{verb} {q}".strip() if q else verb
    path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or inp.get("url")
    if path:
        target = str(path).strip().splitlines()[0]
        # Show just the file name, not the full path (URLs/patterns kept whole).
        if "/" in target and "://" not in target:
            target = Path(target).name
        return f"{verb} {target}".strip()
    return verb


def activity_summary(event: dict) -> Optional[str]:
    """A short 'what is it doing now' string from an assistant event: a tool action
    (e.g. ``Editing foo.py``) or the first line of narration text."""
    content = (event.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_use" and b.get("name") and b.get("name") != _STRUCTURED_TOOL:
            return _tool_activity(b["name"], b.get("input") or {})
    for t in assistant_texts(event):
        line = t.strip().splitlines()[0] if t.strip() else ""
        if line:
            return line[:200]
    return None


def _claude_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def read_transcript_command(session_id: str) -> Optional[dict]:
    """Fallback source: find the session transcript by id and return the LAST command
    (recorded as a ``StructuredOutput`` tool_use). None if not found / no command."""
    if not session_id:
        return None
    matches = list(_claude_projects_dir().glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    path = max(matches, key=lambda p: p.stat().st_mtime)
    last: Optional[dict] = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if (
                    isinstance(b, dict)
                    and b.get("type") == "tool_use"
                    and b.get("name") == _STRUCTURED_TOOL
                    and is_command(b.get("input"))
                ):
                    last = b["input"]
    except OSError:
        return None
    return last
