"""ClaudeService — drives the Claude CLI in headless mode (03).

Mode A (generation: authoring/editing docs & tasks, chat, addressing comments) is
implemented here. Mode B (stateful execution sessions) + the MCP tool server land with the
Execution Engine (07).

Design (validated against CLI v2.1.173 + the permissions docs):
- Generation gives Claude **read access to the whole repo** (`cwd = repo root` + the
  *generation* permissions profile compiled to `--settings`, 09) and the prompt instructs it
  to read `CLAUDE.md`/spec/tasks/source first. Writes are denied — Claude returns text; *we*
  write files.
- One-shot/turn calls use `--output-format json`; pass `session_id` to resume a doc chat.
- No `--max-turns` in this CLI — bound with a subprocess timeout.
- Prompts are Jinja2 templates in the top-level `prompts/` dir (09), rendered by PromptLibrary.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import CamelModel, Comment, DocType, PermissionRequest
from ..storage import StorageService
from ..storage import paths
from .permissions import build_cli_permissions
from .prompts import PromptLibrary

# Rough character budget for any inline content we still pass (e.g. a doc body in chat).
_BODY_BUDGET = 200_000

# Promptly's own app root (the dir containing the ``api`` package) — used as
# PYTHONPATH so the CLI's child helpers (MCP server, hook) can import ``api.*``.
_APP_ROOT = Path(__file__).resolve().parents[2]

# Edit-family tool names the PreToolUse hook gates by path.
_EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


@dataclass
class RunSpec:
    """A fully-built ``claude -p`` execution command for the run loop (07).

    ExecutionManager owns the subprocess (so it can register + kill it); this just
    carries everything needed to spawn it.
    """

    args: list[str]
    env: dict[str, str]
    cwd: str


class ClaudeError(Exception):
    """The CLI failed or returned an error result."""


class GeneratedDoc(CamelModel):
    name: str
    description: str
    body: str


class ChatTurn(CamelModel):
    reply: str
    revised_body: Optional[str] = None
    session_id: Optional[str] = None


class TaskStub(CamelModel):
    name: str
    description: str = ""
    task_group: Optional[str] = None
    depends_on: list[str] = []  # by task name


class GenResult(CamelModel):
    text: str
    session_id: Optional[str] = None
    cost: Optional[float] = None


class ClaudeService:
    def __init__(
        self,
        storage: StorageService,
        *,
        cli_path: str = "claude",
        default_model: str = "claude-opus-4-8",
        timeout: float = 600.0,
        prompts: Optional[PromptLibrary] = None,
        internal_token: str = "",
        api_url: str = "http://127.0.0.1:8000",
        python: Optional[str] = None,
    ) -> None:
        self.storage = storage
        self.cli = cli_path
        self.default_model = default_model
        self.timeout = timeout
        self.prompts = prompts or PromptLibrary()
        # Execution-session config (07): the helpers Claude spawns call back here.
        self.internal_token = internal_token
        self.api_url = api_url
        self.python = python or sys.executable

    # ── CLI invocation ──────────────────────────────────────────────────────────

    async def _invoke(
        self,
        prompt: str,
        *,
        cwd: str,
        settings_json: Optional[str] = None,
        permission_mode: Optional[str] = None,
        add_dirs: Optional[list[str]] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> GenResult:
        args = [
            self.cli, "-p", prompt,
            "--output-format", "json",
            "--model", model or self.default_model,
        ]
        if settings_json:
            args += ["--settings", settings_json]
        if permission_mode:
            args += ["--permission-mode", permission_mode]
        for d in add_dirs or []:
            args += ["--add-dir", d]
        if session_id:
            args += ["--resume", session_id]

        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ClaudeError(f"claude CLI timed out after {self.timeout}s")

        if proc.returncode != 0:
            detail = err.decode(errors="replace")[:2000] or out.decode(errors="replace")[:2000]
            raise ClaudeError(f"claude CLI exited {proc.returncode}: {detail}")
        try:
            data = json.loads(out.decode())
        except json.JSONDecodeError as e:
            raise ClaudeError(f"could not parse CLI output: {e}; raw={out[:500]!r}")
        if data.get("is_error"):
            raise ClaudeError(f"claude returned an error: {data.get('result')}")
        return GenResult(
            text=data.get("result", ""),
            session_id=data.get("session_id"),
            cost=data.get("total_cost_usd"),
        )

    def _gen_cli_args(self, root: str, project: str) -> dict:
        """Generation profile (09): cwd = repo root, repo-wide reads, writes denied."""
        cfg = self.storage.read_permissions(root, project)
        cli = build_cli_permissions(cfg, "generation", repo_root=root)
        return {
            "cwd": root,
            "settings_json": cli.settings_json,
            "permission_mode": cli.permission_mode,
            "add_dirs": cli.add_dirs,
        }

    def _project_path(self, root: str, project: str) -> str:
        return str(paths.project_dir(root, project)) + "/"

    # ── Mode B — execution sessions (07) ─────────────────────────────────────────

    def render_execute_prompt(
        self, root: str, project: str, *, task_name: str, task_file: str,
        worktree: str, dependency_names: list[str],
    ) -> str:
        # Inline the task spec (Claude must have it verbatim). The project spec and
        # sibling docs/tasks are read by path from the worktree's own copies (the
        # worktree is a checkout containing the committed project docs), so reads stay
        # confined to the worktree.
        from pathlib import Path

        pdir = paths.project_dir(root, project)
        tf = pdir / task_file
        task_spec = tf.read_text(encoding="utf-8")[:_BODY_BUDGET] if tf.exists() else ""
        proj_in_wt = Path(worktree) / pdir.relative_to(root)
        return self.prompts.render(
            "execute_task",
            project_name=project,
            task_name=task_name,
            task_spec=task_spec,
            project_spec_path=str(proj_in_wt / "project.md"),
            docs_dir=str(proj_in_wt / "docs"),
            tasks_dir=str(proj_in_wt / "tasks"),
            worktree=worktree,
            dependency_names=dependency_names,
        )

    def build_run_command(
        self,
        root: str,
        project: str,
        *,
        execution_id: str,
        worktree: str,
        prompt: str,
        session_id: Optional[str] = None,
        granted: Optional[list[PermissionRequest]] = None,
    ) -> RunSpec:
        """Compile a build-session ``claude -p`` invocation (07).

        Read scope is explicit: the project's living ``docs/`` and ``tasks/`` dirs
        (via ``--add-dir``) plus the worktree (cwd). Write scope is the worktree
        only, enforced by the PreToolUse hook (hard deny outside, or — if the
        profile sets ``ask_fallback`` — routed to the user). The hook's deny is
        honored even under ``auto`` (the default), so auto runs unattended *and*
        scoped. Only ``bypassPermissions`` drops the hook entirely (fully unscoped).
        ``granted`` carries permissions already approved on a paused run so a
        resumed run pre-allows them.
        """
        cfg = self.storage.read_permissions(root, project)
        profile = cfg.execution
        cli = build_cli_permissions(cfg, "execution", repo_root=root)
        settings = json.loads(cli.settings_json)
        allow: list[str] = settings["permissions"]["allow"]
        skip_hook = cli.permission_mode == "bypassPermissions"

        # Read scope = the worktree only (cwd). The worktree is a checkout that
        # already contains the codebase AND the committed project docs (project.md,
        # docs/, tasks/ — committed just before the run), so nothing outside it needs
        # to be added. No --add-dir of the repo/project dir => no executions/ or
        # whole-repo exposure. Users can still widen via additionalReadDirs.
        read_dirs = list(cfg.additional_read_dirs)
        settings["permissions"]["additionalDirectories"] = read_dirs

        callback_env = {
            "PROMPTLY_API_URL": self.api_url,
            "PROMPTLY_PROJECT": project,
            "PROMPTLY_EXECUTION_ID": execution_id,
            "PROMPTLY_TOKEN": self.internal_token,
        }
        env = {
            **os.environ,
            "PYTHONPATH": str(_APP_ROOT),
            **callback_env,
        }

        extra_tools: list[str] = []
        if not skip_hook:
            # Write boundary: the PreToolUse hook gates the edit tools to the
            # worktree. ask_fallback => route out-of-scope edits to the user (and
            # carry forward already-granted paths); otherwise hard-deny them. Bash
            # is intentionally not gated (runs in the worktree cwd).
            hook_mode = "ask" if profile.ask_fallback else "deny"
            if hook_mode == "ask":
                allowed_paths: list[str] = []
                for g in granted or []:
                    if g.tool in _EDIT_TOOLS:
                        path = str(g.request.get("path", "")).strip()
                        if path:
                            allowed_paths.append(os.path.realpath(path))
                            extra_tools.append(f"{g.tool}({path})")
                allow.extend(extra_tools)
                env["PROMPTLY_ALLOWED_PATHS"] = json.dumps(allowed_paths)

            hook_cmd = f"{_shquote(self.python)} -m api.hooks.pretooluse"
            settings["hooks"] = {
                "PreToolUse": [{
                    "matcher": "Write|Edit|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": hook_cmd, "timeout": 60}],
                }]
            }
            env["PROMPTLY_WORKTREE"] = worktree
            env["PROMPTLY_HOOK_MODE"] = hook_mode

        mcp_config = {
            "mcpServers": {
                "promptly": {
                    "command": self.python,
                    "args": ["-m", "api.mcp_server"],
                    "env": {**callback_env, "PYTHONPATH": str(_APP_ROOT)},
                }
            }
        }

        args = [
            self.cli, "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--model", self.default_model,
            "--settings", json.dumps(settings),
            "--permission-mode", cli.permission_mode,
            "--mcp-config", json.dumps(mcp_config),
            "--strict-mcp-config",
        ]
        for d in read_dirs:
            args += ["--add-dir", d]
        if extra_tools:
            args += ["--allowedTools", *extra_tools]
        if session_id:
            args += ["--resume", session_id]
        return RunSpec(args=args, env=env, cwd=worktree)

    # ── Mode A — generation ──────────────────────────────────────────────────────

    async def generate_document(
        self,
        *,
        root: str,
        project: str,
        prompt: str,
        type: DocType,
        depends_on: Optional[list[str]] = None,
        name_hint: Optional[str] = None,
    ) -> GeneratedDoc:
        type_val = type.value if isinstance(type, DocType) else type
        template = {
            DocType.project_spec.value: "generate_project_spec",
            DocType.task.value: "generate_task",
            DocType.doc.value: "generate_doc",
        }.get(type_val, "generate_doc")

        dependency_names: list[str] = []
        if depends_on:
            tasks = self.storage.read_metadata(root, project, "tasks")
            dependency_names = [tasks[d].name for d in depends_on if d in tasks]

        rendered = self.prompts.render(
            template,
            project_name=project,
            project_path=self._project_path(root, project),
            repo_root=root,
            user_request=prompt,
            name_hint=name_hint,
            dependency_names=dependency_names,
        )
        gen_args = self._gen_cli_args(root, project)
        result = await self._invoke(rendered, **gen_args)
        parsed = _parse_structured(result.text)
        last_text = result.text
        if parsed is None:
            retry = await self._invoke(
                rendered + '\n\nReturn ONLY the JSON object {"name","description","body"}.',
                **gen_args,
            )
            parsed = _parse_structured(retry.text)
            last_text = retry.text
        if parsed is not None:
            return GeneratedDoc(
                name=name_hint or parsed.get("name") or "Untitled",
                description=parsed.get("description", ""),
                body=parsed.get("body", ""),
            )
        # Graceful fallback (09 open Q): the model returned prose, not JSON. Treat
        # the whole reply as the body and derive name/description rather than fail.
        raw = _strip_fences(last_text).strip()
        if not raw:
            raise ClaudeError("empty generation output")
        return GeneratedDoc(
            name=name_hint or _derive_name(raw),
            description=_derive_description(raw),
            body=raw,
        )

    async def chat(
        self,
        *,
        root: str,
        project: str,
        doc_type: DocType | str,
        body: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> ChatTurn:
        type_val = doc_type.value if isinstance(doc_type, DocType) else doc_type
        rendered = self.prompts.render(
            "chat_edit",
            project_name=project,
            project_path=self._project_path(root, project),
            repo_root=root,
            doc_type=type_val,
            body=body[:_BODY_BUDGET],
            message=message,
        )
        gen_args = self._gen_cli_args(root, project)
        result = await self._invoke(rendered, session_id=session_id, **gen_args)
        parsed = _parse_structured(result.text, require="reply")
        if parsed is None:
            # Treat the raw text as a plain reply with no body change.
            return ChatTurn(reply=_strip_fences(result.text).strip() or "(no reply)",
                            revised_body=None, session_id=result.session_id)
        return ChatTurn(
            reply=str(parsed.get("reply", "")),
            revised_body=parsed.get("revisedBody") or None,
            session_id=result.session_id,
        )

    async def plan_tasks(self, *, root: str, project: str) -> list[TaskStub]:
        """Read the project spec + repo and return a task breakdown (stubs)."""
        rendered = self.prompts.render(
            "plan_tasks",
            project_name=project,
            project_path=self._project_path(root, project),
            repo_root=root,
        )
        result = await self._invoke(rendered, **self._gen_cli_args(root, project))
        parsed = _parse_structured(result.text, require="tasks")
        items = (parsed or {}).get("tasks") if parsed else None
        if not isinstance(items, list):
            raise ClaudeError("could not parse task breakdown")
        stubs: list[TaskStub] = []
        for it in items:
            if isinstance(it, dict) and it.get("name"):
                stubs.append(TaskStub.model_validate(it))
        if not stubs:
            raise ClaudeError("task breakdown was empty")
        return stubs

    async def address_comments(
        self,
        *,
        root: str,
        project: str,
        body: str,
        comments: list[Comment],
    ) -> str:
        rendered = self.prompts.render(
            "address_comments",
            project_name=project,
            project_path=self._project_path(root, project),
            repo_root=root,
            body=body,
            comments=[
                {"quote": c.anchor.quote, "kind": c.kind, "body": c.body}
                for c in comments
            ],
        )
        result = await self._invoke(rendered, **self._gen_cli_args(root, project))
        return _strip_fences(result.text).strip()


# ── helpers ──────────────────────────────────────────────────────────────────────


def _bash_patterns(allow: list[str]) -> list[str]:
    """Extract fnmatch globs from ``Bash(<glob>)`` allow entries for the hook."""
    out: list[str] = []
    for entry in allow:
        if entry.startswith("Bash(") and entry.endswith(")"):
            out.append(entry[5:-1].strip())
    return out


def _shquote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t


def _parse_structured(text: str, require: str = "body") -> Optional[dict]:
    """Leniently parse a JSON object (containing key ``require``) from model text."""
    candidate = _strip_fences(text).strip()
    for snippet in (candidate, _first_object(candidate)):
        if not snippet:
            continue
        try:
            obj = json.loads(snippet)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and require in obj:
            return obj
    return None


def _first_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else ""


def _derive_name(body: str) -> str:
    """Best-effort title for a doc when the model didn't give structured metadata:
    the first Markdown H1, else the first non-empty line, truncated."""
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:80] or "Untitled"
    for line in body.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:80]
    return "Untitled"


def _derive_description(body: str) -> str:
    """First non-heading, non-empty line, truncated."""
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s[:140]
    return ""
