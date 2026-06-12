"""ExecutionManager + SSE bus (07).

Runs a task: creates an isolated git worktree, spawns a stateful ``claude -p`` build
session (MCP progress server + PreToolUse approval hook attached), and persists
everything to ``executions/<id>/`` while broadcasting over SSE.

Interaction model (kill-and-resume, decided with the user): the session is **not**
held open waiting on the user. When Claude asks a question or trips a permission
request, the helper records it to ``progress.json`` and we **kill** the subprocess;
when the user answers/approves we re-spawn with ``--resume <sessionId>`` (and, for a
granted permission, the tool added to ``--allowedTools``). All state lives on disk,
so this survives a server restart.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import AsyncIterator, Optional

from collections import defaultdict

from ..models import ProgressState, ProgressStatus, RelatedPR, TaskStatus
from ..storage import StorageService, NotFoundError
from ..storage import paths
from . import worktree
from .claude import ClaudeService


class SSEBus:
    """In-memory pub/sub keyed by execution id. Each subscriber gets its own
    asyncio queue; publishers fan out to all subscribers for that id."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, execution_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[execution_id].add(q)
        return q

    def unsubscribe(self, execution_id: str, q: asyncio.Queue) -> None:
        self._subs[execution_id].discard(q)
        if not self._subs[execution_id]:
            self._subs.pop(execution_id, None)

    def publish(self, execution_id: str, event: str, data: dict) -> None:
        for q in self._subs.get(execution_id, set()):
            q.put_nowait({"event": event, "data": data})


class ExecutionManager:
    def __init__(
        self,
        storage: StorageService,
        bus: SSEBus | None = None,
        claude: ClaudeService | None = None,
    ) -> None:
        self.storage = storage
        self.bus = bus or SSEBus()
        self.claude = claude
        # Live subprocesses + why we last interrupted them, keyed by execution id.
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._interrupt: dict[str, str] = {}
        self._tasks: set[asyncio.Task] = set()

    # ── SSE helpers ──────────────────────────────────────────────────────────────

    def publish_progress(self, execution_id: str, event: str, state: ProgressState) -> None:
        self.bus.publish(execution_id, event, state.model_dump(by_alias=True))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def stop(self, execution_id: str, reason: str) -> None:
        """Record why and kill the running subprocess (called by internal callbacks
        on ask/permission/report-done, and by cancel)."""
        self._interrupt[execution_id] = reason
        proc = self._procs.get(execution_id)
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    # ── Start ────────────────────────────────────────────────────────────────────

    async def start(self, root: str, project: str, task_id: str) -> ProgressState:
        if self.claude is None:
            raise RuntimeError("ExecutionManager requires a ClaudeService")
        task = self.storage.get_entry(root, project, "tasks", task_id)  # 404s if missing

        execution_id = _uuid()
        self.storage.create_execution(root, project, execution_id, task_id)
        self.storage.ensure_gitignore(root)

        # Commit the project's docs + pull the latest base so the worktree starts
        # from the current, shared state (07).
        base_branch = self._prepare_base(root, project)

        wt = str(paths.worktree_path(root, project, execution_id))
        from ..storage.slug import slugify
        branch = worktree.branch_name(slugify(task.name), execution_id)
        base_sha = worktree.add_worktree(root, wt, branch, base=base_branch)
        self.storage.set_execution_meta(
            root, project, execution_id, branch=branch, base_sha=base_sha
        )

        # Two-way link: task -> execution, status in_progress.
        self.storage.patch_metadata(
            root, project, "tasks", task_id,
            {"executionId": execution_id, "status": TaskStatus.in_progress.value},
        )

        deps = [self.storage.get_entry(root, project, "tasks", d).name
                for d in task.depends_on
                if (self.storage.read_metadata(root, project, "tasks").get(d))]
        prompt = self.claude.render_execute_prompt(
            root, project, task_name=task.name, task_file=task.file,
            worktree=wt, dependency_names=deps,
        )
        self._spawn(self._run(root, project, execution_id, task_id, prompt))
        return self.storage.read_progress(root, project, execution_id)

    # ── Run loop ─────────────────────────────────────────────────────────────────

    async def _run(
        self, root: str, project: str, execution_id: str, task_id: str,
        prompt: str, *, session_id: Optional[str] = None,
    ) -> None:
        """Spawn one build-session process and drive it to its next pause point.

        Returns when the process exits; finalization depends on *why* it exited
        (report_done / awaiting input / natural exit / crash / cancel)."""
        wt = str(paths.worktree_path(root, project, execution_id))
        granted = [p for p in self.storage.read_progress(root, project, execution_id)
                   .pending_permissions if p.decision == "allow"]
        spec = self.claude.build_run_command(
            root, project, execution_id=execution_id, worktree=wt,
            prompt=prompt, session_id=session_id, granted=granted,
        )

        self._interrupt.pop(execution_id, None)
        state = self.storage.set_execution_status(
            root, project, execution_id, ProgressStatus.running
        )
        self.publish_progress(execution_id, "status", state)

        proc = await asyncio.create_subprocess_exec(
            *spec.args, cwd=spec.cwd, env=spec.env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._procs[execution_id] = proc

        captured = {"session": session_id is not None}
        stderr_buf: list[bytes] = []

        def on_event(evt: dict) -> None:
            if not captured["session"]:
                sid = evt.get("session_id")
                if sid:
                    self.storage.set_execution_meta(
                        root, project, execution_id, session_id=sid)
                    captured["session"] = True

        async def drain_stdout() -> None:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    on_event(json.loads(line))
                except json.JSONDecodeError:
                    continue

        async def drain_stderr() -> None:
            assert proc.stderr is not None
            stderr_buf.append(await proc.stderr.read())

        try:
            await asyncio.gather(drain_stdout(), drain_stderr())
            await proc.wait()
        finally:
            self._procs.pop(execution_id, None)

        reason = self._interrupt.pop(execution_id, None)
        stderr = b"".join(stderr_buf).decode(errors="replace")[-2000:]
        await self._finalize(root, project, execution_id, task_id,
                             reason, proc.returncode, stderr)

    async def _finalize(
        self, root: str, project: str, execution_id: str, task_id: str,
        reason: Optional[str], returncode: Optional[int], stderr: str,
    ) -> None:
        if reason == "input":
            # Paused for the user; status/pending already recorded by the callback.
            return
        if reason == "cancel":
            state = self.storage.set_execution_status(
                root, project, execution_id, ProgressStatus.failed,
                error="cancelled by user")
            self.publish_progress(execution_id, "status", state)
            return

        done = self.storage.read_progress(root, project, execution_id).done_summary
        if reason == "done" or done or returncode == 0:
            self._complete(root, project, execution_id, task_id, done or "")
            return

        # Crashed / non-zero exit with no pause.
        state = self.storage.set_execution_status(
            root, project, execution_id, ProgressStatus.failed,
            error=stderr or f"build process exited {returncode}")
        self.publish_progress(execution_id, "status", state)

    def _complete(
        self, root: str, project: str, execution_id: str, task_id: str, summary: str
    ) -> None:
        wt = str(paths.worktree_path(root, project, execution_id))
        task = self.storage.get_entry(root, project, "tasks", task_id)
        message = f"{task.name}\n\n{summary}".strip() if summary else task.name
        try:
            worktree.commit_all(wt, message)
        except worktree.GitError:
            pass  # nothing to commit / already committed — not fatal
        state = self.storage.set_execution_status(
            root, project, execution_id, ProgressStatus.completed)
        self.storage.set_status(root, project, task_id, TaskStatus.in_review)
        self.publish_progress(execution_id, "status", state)

    # ── Base sync (07) ─────────────────────────────────────────────────────────

    def _prepare_base(self, root: str, project: str) -> str:
        """Commit the project's docs, then pull (+push) the base branch so the next
        worktree op starts from the current shared state. Returns the base branch."""
        from ..storage.slug import slugify

        worktree.commit_paths(
            root, [f"projects/{slugify(project)}"], f"Promptly: update {project} docs")
        branch = worktree.current_branch(root)
        worktree.pull_base(root, branch)
        worktree.push_base(root, branch)
        return branch

    def _sync_for_resume(self, root: str, project: str, execution_id: str) -> str:
        """Pull the latest base and merge it into the worktree before resuming. If
        the merge conflicts, return an instruction telling the build session to
        resolve them first; otherwise return an empty string."""
        branch = self._prepare_base(root, project)
        wt = str(paths.worktree_path(root, project, execution_id))
        result = worktree.sync_worktree(wt, branch)
        if not result["conflicts"]:
            return ""
        files = ", ".join(result["conflicts"])
        return (
            "NOTE: the base branch advanced and merging it into your worktree produced "
            f"merge conflicts in: {files}. These files contain Git conflict markers "
            "(<<<<<<< / ======= / >>>>>>>). First resolve EVERY conflict sensibly "
            "(preserve both the base changes and your task's changes), then run "
            "`git add` on the resolved files and `git commit --no-edit` to finish the "
            "merge. Only then continue with the request below.\n\n"
        )

    # ── Resume paths ─────────────────────────────────────────────────────────────

    async def answer(
        self, root: str, project: str, execution_id: str,
        question_id: str, answer: str,
    ) -> ProgressState:
        prog = self.storage.read_progress(root, project, execution_id)
        if prog is None:
            raise NotFoundError(f"execution {execution_id} not found")
        _, q = self.storage.answer_question(root, project, execution_id, question_id, answer)
        sync = self._sync_for_resume(root, project, execution_id)
        prompt = sync + (
            "The user answered your question.\n\n"
            f"Question: {q.question}\nAnswer: {answer}\n\nContinue building the task."
        )
        self._spawn(self._run(root, project, execution_id, prog.task_id,
                              prompt, session_id=prog.session_id))
        return self.storage.read_progress(root, project, execution_id)

    async def decide_permission(
        self, root: str, project: str, execution_id: str,
        request_id: str, decision: str,
    ) -> ProgressState:
        prog = self.storage.read_progress(root, project, execution_id)
        if prog is None:
            raise NotFoundError(f"execution {execution_id} not found")
        _, pr = self.storage.decide_permission(
            root, project, execution_id, request_id, decision)
        sync = self._sync_for_resume(root, project, execution_id)
        if decision == "allow":
            prompt = sync + (
                f"The user approved your request to use {pr.tool}. "
                "Retry that action and continue building the task."
            )
        else:
            prompt = sync + (
                f"The user denied your request to use {pr.tool}. Do not attempt it "
                "again; find another approach, or call ask_question if you are stuck. "
                "Continue."
            )
        self._spawn(self._run(root, project, execution_id, prog.task_id,
                              prompt, session_id=prog.session_id))
        return self.storage.read_progress(root, project, execution_id)

    async def feedback(
        self, root: str, project: str, execution_id: str, message: str,
    ) -> ProgressState:
        prog = self.storage.read_progress(root, project, execution_id)
        if prog is None:
            raise NotFoundError(f"execution {execution_id} not found")
        # Back to in_progress; the done marker no longer applies.
        self.storage.set_done_summary(root, project, execution_id, "")
        self.storage.set_status(root, project, prog.task_id, TaskStatus.in_progress)
        sync = self._sync_for_resume(root, project, execution_id)
        prompt = sync + (
            "The user reviewed your work and left feedback:\n\n"
            f"{message}\n\nAddress it, then call report_done again when finished."
        )
        self._spawn(self._run(root, project, execution_id, prog.task_id,
                              prompt, session_id=prog.session_id))
        return self.storage.read_progress(root, project, execution_id)

    async def cancel(self, root: str, project: str, execution_id: str) -> ProgressState:
        self.stop(execution_id, "cancel")
        if execution_id not in self._procs:  # nothing running -> mark failed directly
            state = self.storage.set_execution_status(
                root, project, execution_id, ProgressStatus.failed,
                error="cancelled by user")
            self.publish_progress(execution_id, "status", state)
            return state
        return self.storage.read_progress(root, project, execution_id)

    # ── PR + diff ────────────────────────────────────────────────────────────────

    async def create_pr(self, root: str, project: str, execution_id: str) -> dict:
        prog = self.storage.read_progress(root, project, execution_id)
        if prog is None or not prog.branch:
            raise NotFoundError(f"execution {execution_id} not found")
        wt = str(paths.worktree_path(root, project, execution_id))
        task = self.storage.get_entry(root, project, "tasks", prog.task_id)
        worktree.push_branch(wt, prog.branch)
        title = task.name
        body = (prog.done_summary or task.description or "").strip()
        proc = subprocess.run(
            ["gh", "pr", "create", "--head", prog.branch,
             "--title", title, "--body", body or title],
            cwd=wt, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"gh pr create failed: {proc.stderr.strip() or proc.stdout.strip()}")
        url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        number = _pr_number(url)
        pr = RelatedPR(url=url, number=number, state="open")
        existing = [p.model_dump(by_alias=True) for p in task.related_prs]
        existing.append(pr.model_dump(by_alias=True))
        self.storage.patch_metadata(
            root, project, "tasks", prog.task_id, {"relatedPrs": existing})
        return pr.model_dump(by_alias=True)

    async def diff(self, root: str, project: str, execution_id: str) -> dict:
        prog = self.storage.read_progress(root, project, execution_id)
        if prog is None or not prog.base_sha:
            raise NotFoundError(f"execution {execution_id} not found")
        wt = str(paths.worktree_path(root, project, execution_id))
        return worktree.diff(wt, prog.base_sha)

    # ── Startup recovery ─────────────────────────────────────────────────────────

    def mark_orphans_failed(self) -> None:
        """In-flight runs die with the server. On startup, flip any execution still
        marked running/awaiting_input to failed so the user can retry (07 open Q)."""
        live = {ProgressStatus.running.value, ProgressStatus.awaiting_input.value}
        for proj in self.storage.list_projects():
            for eid in self.storage.list_executions(proj.root, proj.name):
                prog = self.storage.read_progress(proj.root, proj.name, eid)
                if prog and prog.status in live:
                    self.storage.set_execution_status(
                        proj.root, proj.name, eid, ProgressStatus.failed,
                        error="orphaned: server restarted while running")

    # ── SSE stream ───────────────────────────────────────────────────────────────

    async def stream(self, root: str, project: str, execution_id: str) -> AsyncIterator[dict]:
        """Replay the current progress snapshot, then live events. Survives
        reconnects because state always lives in progress.json."""
        snapshot = self.storage.read_progress(root, project, execution_id)
        if snapshot is not None:
            yield {"event": "snapshot", "data": snapshot.model_dump(by_alias=True)}
        q = self.bus.subscribe(execution_id)
        try:
            while True:
                yield await q.get()
        finally:
            self.bus.unsubscribe(execution_id, q)


# ── helpers ──────────────────────────────────────────────────────────────────────


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def _pr_number(url: str) -> int:
    try:
        return int(url.rstrip("/").rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return 0
