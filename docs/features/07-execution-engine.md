# 07 — Execution Engine

**Depends on:** [01](./01-data-model-and-storage.md), [02](./02-python-api-server.md),
[03 Claude CLI](./03-claude-cli-integration.md), [09 Prompts & Permissions](./09-prompts-and-permissions.md).
**Blocks:** [08 Build Tab](./08-build-tab.md).

The backend that runs a task: creates an isolated git worktree, drives a **backend-owned
turn loop** of Claude build turns that report progress via a `--json-schema` **structured-output
command** each turn (no MCP), persists everything to `executions/<execution-id>/`, and
broadcasts live updates over SSE. This is the most complex backend piece — build it after the
CLI wrapper (03) works for one-shot generation.

**Turn loop, backend-driven.** Each turn is a `claude -p` process that does real work with its
tools and returns ONE command (`step_complete` / `revise_steps` / `question` / `issue` / `done`
/ `thinking`). The engine reads the command (from the turn's `structured_output`, or the session
transcript as a fallback), applies it, and `--resume`s for the next turn. Because the loop lives
in uvicorn — not the client — progress continues whether or not a Build tab is open.

**Pauses are kill-and-resume.** A `question`/`issue` command pauses the loop (`awaiting_input`);
a **permission request** (the one remaining child-process callback, from the `PreToolUse` hook)
records into `progress.json` and **kills the turn**. The user's response re-spawns with
`--resume <sessionId>` (and, for a *granted* permission, the tool added to `--allowedTools`).

**Errors never auto-resume.** A turn that returns no valid command (Anthropic down,
connectivity, CLI crash) or a server restart marks the execution `failed` with the message
(keeping the session), flags the task so the Build sidebar shows it **red**, and the user
resumes with **Try again** (`POST /executions/{id}/resume`). All state lives on disk, so this
survives a server restart. uvicorn stays the single writer of `progress.json`.

## Lifecycle
```
pending ──start──▶ in_progress ──done cmd──▶ in_review
   ▲                   │  ▲                          │
   │       question/issue │ answer          feedback│  create PR
   │                   ▼  │                          ▼
   │             awaiting_input               (PR created) ──review comments──▶ in_progress
   └──────────────────────────────────────────────────────────────────────────┘
```
Task `status` and execution `progress.status` are linked but distinct: task status drives
the UI (Plan/Build), `progress.status` (`running | awaiting_input | completed | failed`)
tracks the run loop.

## Starting an execution (`POST /executions {taskId}`)
1. Generate `executionId` (uuid). Create `executions/<id>/`.
2. **Gitignore:** ensure the root `.gitignore` ignores `projects/*/executions/` — the whole
   execution tree is local-only runtime state (worktrees + progress/comments), so committing
   the project's docs never sweeps it in. Idempotent. Done at project creation (02) too.
3. **Prepare the base** (so the worktree starts from current, shared state — runs on *every*
   start and resume): commit the project's docs (`git add -- projects/<name>` + commit; only
   `project.md`/`docs/`/`tasks/` are versioned), then **pull** the base branch fast-forward
   from its upstream if one exists ("check for new changes to pull"), then **push** the base
   if a remote exists. All best-effort — no remote ⇒ local-only.
4. **Worktree:** create a branch (`promptly/<task-slug>-<short-id>`) and a worktree at
   `executions/<id>/worktree/` off the **current branch**'s freshly-updated HEAD:
   `git -C <root> worktree add -b <branch> <execdir>/worktree <base-branch>`. The worktree is
   a checkout, so it already contains the committed project docs + the codebase.
5. Write initial `progress.json` (`status: running`, `branch`, `baseSha`, `sessionId: null`).
6. Link both ways: set `task.executionId = id` and `task.status = in_progress`;
   `progress.taskId = id`.
7. Kick off the **plan-then-run** background task and return `executionId` immediately so the
   UI can subscribe to the stream.

## Planning phase (before the build session)
Execution starts with a short **generation call**
(`ClaudeService.plan_execution_steps`, `plan_steps.md.j2`, generation profile = repo-wide
reads, no writes) that breaks the task into an ordered list of concrete steps ("research X",
"implement Y", "add tests", "run the suite"). These are seeded into `progress.steps`
(`storage.seed_steps`) **all incomplete except the first, which is set `in_progress`**, and a
`steps` SSE event is emitted so the UI shows the plan immediately. The build session that
follows is given this plan inlined in its prompt — it does **not** re-plan. (If planning
fails, the execution is marked `failed` before any worktree session starts.)

## The run loop (turn-based)
`ExecutionManager._run` loops: each iteration spawns one build turn via
`ClaudeService.build_run_command()` (03) — `cwd = worktree/`, `--output-format stream-json`,
**`--json-schema <command schema>`**, the **execution** permissions profile compiled into
`--settings`/`--permission-mode`/`--add-dir` (09), and the `PreToolUse` hook, all bound to this
`executionId` via env. ExecutionManager owns the subprocess (registry) so it can kill it; it
drains `stream-json` to (a) capture `session_id`, (b) surface the live **activity** line
(`thinking`/`tool_use`/`text` → `progress.activity`, published), and (c) read the turn's
**command** from the final `result` event's `structured_output`.
- **Prompt:** rendered from `execute_task.md.j2` (09). The **task spec is inlined** along with
  the pre-planned step list; the project spec, sibling specs, `CLAUDE.md`, and source are read
  by path **from the worktree's own checkout** (reads confined to the worktree — see
  Permissions). The model does the current step's work with its tools, then returns one command.
- **Dispatch** (`_handle_command`, see `api/services/exec_protocol.py`):
  `step_complete{title}` marks the step `done` + auto-advances the next → resume; `revise_steps`
  replaces the whole plan (preserving ids/timestamps by title) → resume; `thinking` updates the
  activity → resume; `question`/`issue` records a pending question (with `kind`) → **pause**
  (`awaiting_input`); `done` finalizes (below).
- **Command source:** the live `structured_output`; if a turn's process is lost (server restart)
  the command is recovered from the transcript (`~/.claude/projects/*/<session_id>.jsonl`, a
  `tool_use` named `StructuredOutput`).
- **Session id:** captured from `stream-json` and persisted as soon as known (enables `--resume`).
- **Completion (`done`):** **guarded** — if any step is still `done`/`skipped`-incomplete the
  loop resumes the session with the list of remaining steps (it must finish or revise first).
  Once all steps are complete it records `doneSummary`, **commits the worktree once** with a
  generated message, sets `progress.status = completed`, task `status = in_review`, clears the
  task's error flag, emits `status` SSE.
- **Error (no auto-resume):** a turn that returns no valid command (Anthropic/connectivity/CLI
  failure) → `progress.status = failed` with the message, the task's `executionError` flag set
  (sidebar shows red); the user resumes with **Try again** or sends feedback. `cancel` →
  `failed` ("cancelled by user").

## Mid-run interactions (resume the session)
All use `--resume <sessionId>` (03). **Before every resume, re-sync the base** (an execution
can sit `awaiting_input`/`in_review` long enough for the repo + docs to move on): re-run the
*prepare-the-base* step (commit docs, pull, push), then in the worktree `stash` → `merge` the
updated base → `stash pop`. If the merge/pop **conflicts**, prepend an instruction to the
resume prompt telling the build session to resolve the conflict markers, `git add` + `git
commit --no-edit` the merge, *then* carry on — it has worktree write + bash, so it fixes them
inline. If the base hasn't moved, this is a no-op.
- **Answer a question** (`POST /executions/{id}/answer`): record the answer on the pending
  question, resume the session delivering the answer, set `progress.status` back to
  `running`. Claude continues; updates flow as before.
- **Approve/deny a permission request** (`POST /executions/{id}/permission`): see the
  permissions section below — same `awaiting_input` pattern as questions.
- **Feedback** (`POST /executions/{id}/feedback`, from in_review): set task back to
  `in_progress`, resume the session with the feedback message; Claude addresses it and
  eventually `report_done` again.
- **Review PR comments** (in_review → in_progress): pull PR review comments and resume the
  session with them as feedback (same path as above).

## Creating a PR (`POST /executions/{id}/pr`)
From in_review: push the worktree branch and open a PR (via `gh` CLI or the GitHub API).
Record `{url, number, state}` in the task's `relatedPRs`. Keep the worktree so subsequent
PR-comment review can resume work in place.

## Diff data (`GET /executions/{id}/diff`)
For the Build Diff view (08): list changed files and per-file diffs of the worktree vs. its
base, plus the current HEAD commit sha (used to partition `comments.json`). Compute with
`git -C <worktree> diff` / `git status --porcelain` / `git rev-parse HEAD`.

## SSE bus
ExecutionManager keeps an in-memory `dict[execution_id -> subscribers]`. Command dispatch and
loop state changes `publish(execution_id, event)`. The `/executions/{id}/stream` endpoint
(02) subscribes; on connect it first sends the current `progress.json` snapshot, then live
events. Survives reconnects because state is always in `progress.json`.

## Concurrency, cleanup, safety
- Multiple executions can run concurrently (different worktrees/branches) — keep a registry
  of running processes for cancel/cleanup.
- **Cancel:** kill the process tree; mark `failed`; optionally `git worktree remove`.
- **Cleanup:** on task `done`/abandon, optionally remove the worktree (`git worktree remove
  --force`) and prune the branch; keep `progress.json`/`comments.json` for history.
## Permissions model
Driven by the per-project **execution** profile in `permissions.json`, compiled into Claude
CLI `--settings`/`--permission-mode`/`--add-dir` ([09](./09-prompts-and-permissions.md)).

**Default: `auto` mode (unattended) with explicit read/write scoping.** Executions run in
`auto` permission mode — no approval prompts — but with explicit boundaries:
- **Read scope:** the **worktree only** (`cwd`) — no `--add-dir` of the repo/project/`docs`/
  `tasks` at all. The worktree is a checkout that already contains the codebase **and** the
  committed project docs (`project.md`, `docs/`, `tasks/` — committed by the prepare-base step
  just before the run), so everything is readable from within it; `executions/` is never
  exposed. The **task spec is inlined** into the prompt; the project spec + sibling specs are
  read by path from the worktree's own copies. Users can widen with `additionalReadDirs`.
- **Write scope:** the worktree only. The **PreToolUse hook** hard-denies edits whose path is
  outside the worktree (verified: the hook's deny is honored even under `auto`). Bash runs
  unattended in the worktree (`cwd`); it isn't path-gated (OS-level bash sandboxing is out of
  scope), but `auto` mode's own write-sandbox + the worktree cwd keep it contained in practice.
- The system prompt explains this layout to Claude: which paths are read-only references
  (docs/tasks/spec) vs. its read+write sandbox (the worktree).

**Modes.** `auto` (default) = unattended + hook-scoped. `default`/`acceptEdits` also keep the
hook. Set `ask_fallback: true` to route out-of-scope writes to the user (kill-and-resume +
`--allowedTools` on grant) instead of hard-denying. Only `bypassPermissions` drops the hook
entirely (fully unscoped). A future per-command whitelist/blacklist plugs into the hook +
allow/deny rules.

- **Flagged requests go back to the user — via a `PreToolUse` hook, not an MCP tool (ask_fallback only).** This
  CLI has **no `--permission-prompt-tool`** (verified, v2.1.175). Instead the settings we pass
  register a **`PreToolUse` hook** (09): it fires before Write/Edit/Bash calls and decides
  `allow` (in-worktree edits, allow-listed Bash commands) vs. **out of scope** (write/exec
  outside the worktree, a Bash command not on the allowlist). For out-of-scope calls the hook
  POSTs a **permission request** to Promptly's internal API and **denies** the call (fail
  closed even if the callback fails). Reads pass through to the normal repo-wide read flow.
  - The callback appends to `pendingPermissions: [{ id, tool, request, decision: null, askedAt }]`
    in `progress.json`, sets `progress.status = awaiting_input`, emits an SSE `permission`
    event, and **kills the subprocess** (kill-and-resume — the hook does not block).
    `POST /executions/{id}/permission {requestId, decision}` records the decision and
    **re-spawns** with `--resume`; on `allow` the granted tool is added to `--allowedTools`
    (and the hook's allow-set) so the retried action succeeds; on `deny` Claude is told to
    find another approach.
- **Widening access:** the user edits `permissions.json` to grant more (extra read dirs,
  additional allowed tools/commands). Defaults are sensible without it (09).

## Implementation steps
1. Worktree create/remove helpers + idempotent `.gitignore` handling.
2. ExecutionManager: start flow, `progress.json` init, two-way task↔execution linking.
3. SSE bus (pub/sub) + snapshot-on-connect.
4. Turn loop (`build_run_command` with `--json-schema` + `_run`/`_handle_command`) parsing
   structured-output commands; `exec_protocol.py` (schema + transcript fallback).
5. `PreToolUse` approval hook + `pendingPermissions` ↔ `/permission` wiring (09).
6. Answer / feedback / PR-comment resume paths; `resume` (Try again) + startup
   `mark_orphans_interrupted`.
7. Diff endpoint + PR creation.
8. Cancel/cleanup + concurrent-execution registry.
9. Tests: worktree lifecycle, command-parse→progress→SSE path, transcript fallback,
   permission-hook flow, resume flows (mock ClaudeService).

## Resolved decisions
- **Progress protocol:** a `--json-schema` **structured-output command per turn** (no MCP) —
  parsed from the turn's `structured_output`, transcript as fallback. See
  `api/services/exec_protocol.py` and [03](./03-claude-cli-integration.md).
- **Interaction model:** backend-driven turn loop. `question`/`issue` commands pause; permission
  requests are kill-and-resume via the `PreToolUse` hook (the only child-process callback);
  resumes use `--resume` (+ `--allowedTools` for grants).
- **Helper ↔ Promptly channel:** the localhost internal HTTP API now carries only the
  `permission-request` callback (token-guarded). uvicorn is the single writer of `progress.json`.
- **PR tooling:** `gh` CLI (reuses the user's GitHub auth).
- **Errors & recovery (no auto-resume):** a turn that returns no valid command (Anthropic down,
  connectivity, CLI crash) marks the execution `failed` with the message and flags the task red.
  On **server restart**, `mark_orphans_interrupted()` flips still-`running` executions to that
  error state (keeping the session); `awaiting_input` stays paused. The user resumes any error
  with **Try again** (`POST /executions/{id}/resume`), which `--resume`s the loop (reconciling a
  trailing transcript question/issue into a pause instead of re-running).
