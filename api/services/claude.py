"""ClaudeService — drives the Claude CLI in headless mode (03).

Mode A (one-shot generation) is implemented here: docs, task specs, the project
spec, and comment-addressing. Mode B (stateful execution sessions) + the MCP tool
server land with the Execution Engine (07).

Design decisions (validated against Claude CLI v2.1.173):
- One-shot calls use ``--output-format json`` and read the single ``result`` field
  (cleaner than stream-json for non-interactive generation; still yields
  ``session_id`` + cost).
- Generation runs with **all tools disabled**. Empirically, enabling file tools
  makes generation go agentic (multi-turn, tries to write files) and breaks the
  structured ``{name, description, body}`` output. So instead of granting Read +
  ``--add-dir``, the API **inlines** the project docs into the prompt: the model
  still sees the full spec + sibling manifest + dependency bodies, delivered as
  context rather than via a tool. (Sr-staff design review, Option B.)
- ``--max-turns`` does not exist in this CLI version; we bound runtime with a
  subprocess timeout instead.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from ..models import CamelModel, Comment, DocType, MetadataEntry, TaskStatus
from ..storage import StorageService

# Tools we explicitly disable for one-shot generation so it stays single-turn and
# returns clean structured output.
_DISABLED_TOOLS = [
    "Write", "Edit", "NotebookEdit", "Bash", "Read", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task",
]

# Rough character budget for inlined context (Fable guardrail). Comfortably inside
# the context window; we trim in priority order if exceeded.
_CONTEXT_BUDGET = 350_000

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class ClaudeError(Exception):
    """The CLI failed or returned an error result."""


class GeneratedDoc(CamelModel):
    name: str
    description: str
    body: str


class GenResult(CamelModel):
    text: str
    session_id: Optional[str] = None
    cost: Optional[float] = None


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


class ClaudeService:
    def __init__(
        self,
        storage: StorageService,
        *,
        cli_path: str = "claude",
        default_model: str = "claude-opus-4-8",
        timeout: float = 300.0,
    ) -> None:
        self.storage = storage
        self.cli = cli_path
        self.default_model = default_model
        self.timeout = timeout

    # ── CLI invocation ──────────────────────────────────────────────────────────

    async def _invoke(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        model: Optional[str] = None,
        disallowed_tools: Optional[list[str]] = None,
        cwd: Optional[str] = None,
    ) -> GenResult:
        args = [
            self.cli, "-p", prompt,
            "--output-format", "json",
            "--model", model or self.default_model,
        ]
        if system:
            args += ["--append-system-prompt", system]
        if disallowed_tools:
            args += ["--disallowedTools", *disallowed_tools]

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
            raise ClaudeError(
                f"claude CLI exited {proc.returncode}: {err.decode(errors='replace')[:2000]}"
            )
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

    # ── Context inlining ─────────────────────────────────────────────────────────

    def _read_body(self, root: str, project: str, entry: MetadataEntry) -> str:
        path = self.storage._body_abs(root, project, entry.file)  # noqa: SLF001
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def build_context(
        self,
        root: str,
        project: str,
        *,
        dependency_ids: Optional[list[str]] = None,
    ) -> str:
        """Inline the project spec + a manifest of all docs/tasks + full bodies of
        the given dependencies. Trims to a character budget if needed."""
        docs = self.storage.read_metadata(root, project, "docs")
        tasks = self.storage.read_metadata(root, project, "tasks")
        dependency_ids = dependency_ids or []

        # 1. project spec (full) — highest priority.
        spec_block = ""
        spec = next(
            (e for e in docs.values() if e.type == DocType.project_spec.value), None
        )
        if spec is not None:
            body, _ = _split_body(self._read_body(root, project, spec))
            spec_block = f"<file path=\"project.md\">\n{body.strip()}\n</file>\n\n"

        # 2. manifest of siblings (name + description, plus status/deps for tasks).
        manifest_lines: list[str] = []
        for e in docs.values():
            if e.type == DocType.project_spec.value or e.status == TaskStatus.removed.value:
                continue
            manifest_lines.append(f"- (doc) {e.name}: {e.description}")
        for t in tasks.values():
            if t.status == TaskStatus.removed.value:
                continue
            deps = f" depends_on={t.depends_on}" if t.depends_on else ""
            manifest_lines.append(
                f"- (task, {t.status}) {t.name}{deps}: {t.description}"
            )
        manifest_block = ""
        if manifest_lines:
            manifest_block = (
                "<manifest>\nExisting docs and tasks in this project:\n"
                + "\n".join(manifest_lines)
                + "\n</manifest>\n\n"
            )

        # 3. full bodies of direct dependencies.
        dep_blocks: list[str] = []
        for dep_id in dependency_ids:
            t = tasks.get(dep_id)
            if t is None:
                continue
            body, _ = _split_body(self._read_body(root, project, t))
            dep_blocks.append(
                f"<dependency name=\"{t.name}\" file=\"{t.file}\">\n{body.strip()}\n</dependency>"
            )
        dep_block = ("\n\n".join(dep_blocks) + "\n\n") if dep_blocks else ""

        context = spec_block + manifest_block + dep_block
        if len(context) > _CONTEXT_BUDGET:
            # Trim in priority order: drop dependency bodies, then trim manifest.
            context = spec_block + manifest_block
            if len(context) > _CONTEXT_BUDGET:
                context = spec_block[:_CONTEXT_BUDGET]
        if not context:
            return ""
        return "<project_context>\n" + context + "</project_context>\n\n"

    # ── Mode A — one-shot generation ─────────────────────────────────────────────

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
        system = {
            DocType.project_spec.value: "generate_project_spec.md",
            DocType.task.value: "generate_task.md",
            DocType.doc.value: "generate_doc.md",
        }.get(type_val, "generate_doc.md")
        system_prompt = _load_prompt(system)

        context = self.build_context(root, project, dependency_ids=depends_on)
        hint = f"\nSuggested name: {name_hint}\n" if name_hint else ""
        user_prompt = f"{context}<request>\n{prompt}\n</request>\n{hint}"

        result = await self._invoke(
            user_prompt, system=system_prompt, disallowed_tools=_DISABLED_TOOLS
        )
        parsed = _parse_structured(result.text)
        if parsed is None:
            # One stricter retry (almost never fires in tools-off mode).
            retry = await self._invoke(
                user_prompt
                + "\n\nReturn ONLY the JSON object {\"name\",\"description\",\"body\"}.",
                system=system_prompt,
                disallowed_tools=_DISABLED_TOOLS,
            )
            parsed = _parse_structured(retry.text)
        if parsed is None:
            raise ClaudeError("could not parse structured generation output")
        return GeneratedDoc(
            name=name_hint or parsed.get("name") or "Untitled",
            description=parsed.get("description", ""),
            body=parsed.get("body", ""),
        )

    async def address_comments(
        self,
        *,
        root: str,
        project: str,
        body: str,
        comments: list[Comment],
    ) -> str:
        system_prompt = _load_prompt("address_comments.md")
        comment_lines = []
        for c in comments:
            comment_lines.append(
                f"- On «{c.anchor.quote}» ({c.kind}): {c.body}"
            )
        user_prompt = (
            "<document>\n" + body + "\n</document>\n\n"
            "<comments>\n" + "\n".join(comment_lines) + "\n</comments>\n\n"
            "Return the full revised Markdown body."
        )
        result = await self._invoke(
            user_prompt, system=system_prompt, disallowed_tools=_DISABLED_TOOLS
        )
        return _strip_fences(result.text).strip()


# ── helpers ──────────────────────────────────────────────────────────────────────


def _split_body(raw: str) -> tuple[str, list]:
    """Strip the trailing promptly:comments block from a raw .md (we only want the
    body for context). Imported lazily to avoid a cycle at module import."""
    from ..storage import comments as comment_io

    return comment_io.parse_document(raw)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # drop the first fence line (``` or ```json) and the trailing fence.
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -3]
    return t


def _parse_structured(text: str) -> Optional[dict]:
    """Leniently parse a {name, description, body} object out of the model's text."""
    candidate = _strip_fences(text).strip()
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict) and "body" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    # Fallback: find the first {...} span and try that.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(candidate[start : end + 1])
            if isinstance(obj, dict) and "body" in obj:
                return obj
        except json.JSONDecodeError:
            return None
    return None
