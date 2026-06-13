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
from .exec_protocol import (
    activity_summary,
    command_from_result_event,
    read_transcript_command,
)


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
        # Execution ids with a live OR starting run. Maintained synchronously (before
        # the first await) so the liveness monitor can tell a genuinely-dead run apart
        # from one that's mid-spawn. `_procs` alone has a gap: it's only populated after
        # create_subprocess_exec, and planning (phase 1) has no process at all.
        self._active: set[str] = set()

    # ── SSE helpers ──────────────────────────────────────────────────────────────

    def publish_progress(self, execution_id: str, event: str, state: ProgressState) -> None:
        self.bus.publish(execution_id, event, state.model_dump(by_alias=True))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _spawn_tracked(self, execution_id: str, coro) -> None:
        """Spawn a top-level run coroutine, marking the execution active for the whole
        of its lifetime (including any pre-process planning phase)."""
        self._active.add(execution_id)

        async def runner() -> None:
            try:
                await coro
            finally:
                self._active.discard(execution_id)

        self._spawn(runner())

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
        # Plan first (separate MCP-free call), then run the build session. Done in a
        # spawned task so start() returns immediately; steps stream in over SSE.
        self._spawn_tracked(execution_id, self._plan_then_run(
            root, project, execution_id, task_id, task.name, task.file, wt, deps))
        return self.storage.read_progress(root, project, execution_id)

    async def _plan_then_run(
        self, root: str, project: str, execution_id: str, task_id: str,
        task_name: str, task_file: str, worktree_dir: str, deps: list[str],
    ) -> None:
        """Phase 1: ask Claude to break the task into steps and seed them (first
        in_progress). Phase 2: run the build session with the plan inlined."""
        def on_plan_event(evt: dict) -> None:
            if evt.get("type") == "assistant":
                act = activity_summary(evt)
                if act:
                    state = self.storage.set_activity(root, project, execution_id, act)
                    self.publish_progress(execution_id, "progress", state)

        try:
            stubs = await self.claude.plan_execution_steps(
                root=root, project=project, task_name=task_name,
                task_file=task_file, dependency_names=deps, on_event=on_plan_event,
            )
        except Exception as exc:  # planning failed -> mark the execution failed
            state = self.storage.set_execution_status(
                root, project, execution_id, ProgressStatus.failed,
                error=f"planning failed: {exc}")
            self.publish_progress(execution_id, "status", state)
            return

        state = self.storage.seed_steps(
            root, project, execution_id,
            [{"title": s.title, "detail": s.detail} for s in stubs],
        )
        self.publish_progress(execution_id, "steps", state)

        prompt = self.claude.render_execute_prompt(
            root, project, task_name=task_name, task_file=task_file,
            worktree=worktree_dir, dependency_names=deps, steps=state.steps,
        )
        await self._run(root, project, execution_id, task_id, prompt)

    # ── Run loop (turn-based, --json-schema protocol) ────────────────────────────
    #
    # Each turn is one `claude -p` process that does real work with its tools and
    # returns ONE structured-output command (see api/services/exec_protocol.py). We
    # dispatch it and resume for the next turn — entirely backend-driven, so the loop
    # progresses whether or not a Build tab is open. The loop only stops on a pause
    # (question/issue/permission), completion (done), cancel, or an error (the user
    # resumes errors with "Try again").

    _MAX_TURNS = 200  # hard safety cap on turns per _run invocation

    async def _run(
        self, root: str, project: str, execution_id: str, task_id: str,
        prompt: str, *, session_id: Optional[str] = None,
    ) -> None:
        sid = session_id
        next_prompt = prompt
        for _ in range(self._MAX_TURNS):
            self._interrupt.pop(execution_id, None)
            state = self.storage.set_execution_status(
                root, project, execution_id, ProgressStatus.running)
            self.publish_progress(execution_id, "status", state)

            turn = await self._run_turn(
                root, project, execution_id, next_prompt, sid)
            if turn["session_id"] and not sid:
                sid = turn["session_id"]
                self.storage.set_execution_meta(
                    root, project, execution_id, session_id=sid)

            reason = self._interrupt.pop(execution_id, None)
            if reason == "input":
                return  # paused for a permission request (recorded by the hook)
            if reason == "cancel":
                state = self.storage.set_execution_status(
                    root, project, execution_id, ProgressStatus.failed,
                    error="cancelled by user")
                self.publish_progress(execution_id, "status", state)
                return

            cmd = turn["command"]
            if cmd is None:
                cmd = read_transcript_command(sid) if sid else None
            if cmd is None:
                # The turn ended without a valid command — Anthropic/connectivity/CLI
                # error or a crash. Surface it; the user resumes with "Try again".
                self._set_error(
                    root, project, execution_id, task_id,
                    turn["stderr"] or "the AI didn't return a valid response "
                    f"(exit {turn['returncode']}).")
                return

            action = self._handle_command(root, project, execution_id, task_id, cmd)
            if action is None:
                return  # paused (question/issue) or finished (done) or errored
            next_prompt = action  # a continue prompt for the next turn

        self._set_error(root, project, execution_id, task_id,
                        "stopped after too many turns without finishing.")

    async def _run_turn(
        self, root: str, project: str, execution_id: str, prompt: str,
        session_id: Optional[str],
    ) -> dict:
        """Spawn one build turn; stream its live activity; return its command +
        session id + exit info."""
        wt = str(paths.worktree_path(root, project, execution_id))
        granted = [p for p in self.storage.read_progress(root, project, execution_id)
                   .pending_permissions if p.decision == "allow"]
        spec = self.claude.build_run_command(
            root, project, execution_id=execution_id, worktree=wt,
            prompt=prompt, session_id=session_id, granted=granted,
        )

        proc = await asyncio.create_subprocess_exec(
            *spec.args, cwd=spec.cwd, env=spec.env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._procs[execution_id] = proc

        captured: dict = {"session_id": session_id, "command": None}
        stderr_buf: list[bytes] = []

        def on_event(evt: dict) -> None:
            sid = evt.get("session_id")
            if sid:
                captured["session_id"] = sid
            if evt.get("type") == "assistant":
                act = activity_summary(evt)
                if act:
                    self.storage.set_activity(root, project, execution_id, act)
                    self.publish_progress(
                        execution_id, "progress",
                        self.storage.read_progress(root, project, execution_id))
            if evt.get("type") == "result":
                cmd = command_from_result_event(evt)
                if cmd is not None:
                    captured["command"] = cmd

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

        return {
            "command": captured["command"],
            "session_id": captured["session_id"],
            "returncode": proc.returncode,
            "stderr": b"".join(stderr_buf).decode(errors="replace")[-2000:],
        }

    def _handle_command(
        self, root: str, project: str, execution_id: str, task_id: str, cmd: dict,
    ) -> Optional[str]:
        """Apply a structured-output command. Returns a continue-prompt to keep looping,
        or None to stop the loop (paused / done / errored)."""
        ctype = cmd.get("type")
        if ctype == "thinking":
            text = str(cmd.get("text", "")).strip()
            if text:
                state = self.storage.set_activity(root, project, execution_id, text)
                self.publish_progress(execution_id, "progress", state)
            return "Continue."

        if ctype == "step_complete":
            state = self.storage.complete_step(
                root, project, execution_id, title=cmd.get("title"))
            self.publish_progress(execution_id, "steps", state)
            return ("Step recorded. Continue with the next step; return one command when "
                    "you finish it, hit a blocker, or are done.")

        if ctype == "revise_steps":
            steps = cmd.get("steps") if isinstance(cmd.get("steps"), list) else []
            state = self.storage.revise_steps(root, project, execution_id, steps)
            self.publish_progress(execution_id, "steps", state)
            return "Plan updated. Continue with the in-progress step."

        if ctype in ("question", "issue"):
            text = str(cmd.get("question") if ctype == "question" else cmd.get("issue") or "")
            detail = str(cmd.get("detail", "")).strip()
            if detail and ctype == "issue":
                text = f"{text}\n\n{detail}".strip()
            state, _ = self.storage.add_question(
                root, project, execution_id, text or f"(empty {ctype})", kind=ctype)
            self.publish_progress(execution_id, "question", state)
            return None  # pause for the user

        if ctype == "done":
            prog = self.storage.read_progress(root, project, execution_id)
            incomplete = [s.title for s in (prog.steps if prog else [])
                          if s.status not in ("done", "skipped")]
            if incomplete:
                return ("You reported done, but these steps are still incomplete: "
                        + ", ".join(incomplete) + ". Complete them (return step_complete "
                        "for each) or revise the plan (revise_steps), then return done.")
            self._complete(root, project, execution_id, task_id,
                           str(cmd.get("summary", "")))
            return None  # finished

        # Unknown command type — treat as a non-fatal nudge.
        return "Continue. Return one of the documented commands when you reach a reporting point."

    def _set_error(
        self, root: str, project: str, execution_id: str, task_id: str, message: str,
    ) -> None:
        """Put the execution into a user-visible error state (no auto-resume). Flags the
        task so the Build sidebar highlights it red; the user resumes with Try again."""
        state = self.storage.set_execution_status(
            root, project, execution_id, ProgressStatus.failed, error=message)
        try:
            self.storage.patch_metadata(
                root, project, "tasks", task_id, {"executionError": True})
        except NotFoundError:
            pass
        self.publish_progress(execution_id, "status", state)

    def _complete(
        self, root: str, project: str, execution_id: str, task_id: str, summary: str
    ) -> None:
        wt = str(paths.worktree_path(root, project, execution_id))
        task = self.storage.get_entry(root, project, "tasks", task_id)
        message = f"{task.name}\n\n{summary}".strip() if summary else task.name
        if summary:
            self.storage.set_done_summary(root, project, execution_id, summary)
        try:
            worktree.commit_all(wt, message)
        except worktree.GitError:
            pass  # nothing to commit / already committed — not fatal
        state = self.storage.set_execution_status(
            root, project, execution_id, ProgressStatus.completed)
        self.storage.set_status(root, project, task_id, TaskStatus.in_review)
        self.storage.patch_metadata(
            root, project, "tasks", task_id, {"executionError": False})
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
        if q.kind == "issue":
            lead = (f"Regarding the issue you reported (\"{q.question}\"), the user "
                    f"responded:\n\n{answer}\n\nAct on it and continue building the task.")
        else:
            lead = ("The user answered your question.\n\n"
                    f"Question: {q.question}\nAnswer: {answer}\n\nContinue building the task.")
        prompt = sync + lead
        self._spawn_tracked(execution_id, self._run(root, project, execution_id,
                            prog.task_id, prompt, session_id=prog.session_id))
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
                "again; find another approach, or return a question command if you are "
                "stuck. Continue."
            )
        self._spawn_tracked(execution_id, self._run(root, project, execution_id,
                            prog.task_id, prompt, session_id=prog.session_id))
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
            f"{message}\n\nAddress it, then return a done command when finished."
        )
        self._spawn_tracked(execution_id, self._run(root, project, execution_id,
                            prog.task_id, prompt, session_id=prog.session_id))
        return self.storage.read_progress(root, project, execution_id)

    async def resume(self, root: str, project: str, execution_id: str) -> ProgressState:
        """The "Try again" action: clear the error and resume the loop. If a session
        exists, continue it (reconciling a trailing question/issue from the transcript
        into a pause instead); otherwise (e.g. planning failed) re-plan + run."""
        prog = self.storage.read_progress(root, project, execution_id)
        if prog is None:
            raise NotFoundError(f"execution {execution_id} not found")
        if execution_id in self._active:
            return prog  # already running

        try:
            self.storage.patch_metadata(
                root, project, "tasks", prog.task_id, {"executionError": False})
        except NotFoundError:
            pass

        if not prog.session_id:
            task = self.storage.get_entry(root, project, "tasks", prog.task_id)
            wt = str(paths.worktree_path(root, project, execution_id))
            deps = [self.storage.get_entry(root, project, "tasks", d).name
                    for d in task.depends_on
                    if (self.storage.read_metadata(root, project, "tasks").get(d))]
            self._spawn_tracked(execution_id, self._plan_then_run(
                root, project, execution_id, prog.task_id,
                task.name, task.file, wt, deps))
            return self.storage.read_progress(root, project, execution_id)

        # Reconcile: if the last recorded command was a question/issue, pause instead.
        cmd = read_transcript_command(prog.session_id)
        if cmd and cmd.get("type") in ("question", "issue"):
            pending = [q for q in prog.pending_questions if q.answer is None]
            text = str(cmd.get("question") if cmd["type"] == "question"
                       else cmd.get("issue") or "")
            if not any(q.question == text for q in pending):
                state, _ = self.storage.add_question(
                    root, project, execution_id, text or f"(empty {cmd['type']})",
                    kind=cmd["type"])
                self.publish_progress(execution_id, "question", state)
                return state
            state = self.storage.set_execution_status(
                root, project, execution_id, ProgressStatus.awaiting_input)
            self.publish_progress(execution_id, "question", state)
            return state

        prompt = self._sync_for_resume(root, project, execution_id) + (
            "The previous build session was interrupted before finishing. Continue "
            "building the task from where you left off; return one command when you "
            "finish a step, hit a blocker, or are done."
        )
        self._spawn_tracked(execution_id, self._run(
            root, project, execution_id, prog.task_id,
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

    def mark_orphans_interrupted(self) -> None:
        """In-flight runs die with the server. On startup, flip any execution still
        marked ``running`` to an error state (keeping its session) so the user can
        resume it with "Try again"; the task is flagged red in the sidebar.
        ``awaiting_input`` executions stay paused."""
        for proj in self.storage.list_projects():
            for eid in self.storage.list_executions(proj.root, proj.name):
                prog = self.storage.read_progress(proj.root, proj.name, eid)
                if prog and prog.status == ProgressStatus.running.value:
                    self._set_error(
                        proj.root, proj.name, eid, prog.task_id,
                        "interrupted — the server restarted while this was running. "
                        "Click Try again to resume.")

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
