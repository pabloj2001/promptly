# 07 — Execution Engine

**Depends on:** [01](./01-data-model-and-storage.md), [02](./02-python-api-server.md),
[03 Claude CLI](./03-claude-cli-integration.md), [09 Prompts & Permissions](./09-prompts-and-permissions.md).
**Blocks:** [08 Build Tab](./08-build-tab.md).

The backend that runs a task: creates an isolated git worktree, spawns a stateful Claude
session that builds the task and reports progress via MCP tools, persists everything to
`executions/<execution-id>/`, and broadcasts live updates over SSE. This is the most complex
backend piece — build it after the CLI wrapper (03) works for one-shot generation.

**Interaction model — kill-and-resume (not blocking).** When the build session needs the
user (a question or a permission request), we do **not** hold the process open waiting.
A helper records the request into `progress.json`, we set `awaiting_input`, emit SSE, and
**kill the subprocess**. When the user responds, we re-spawn with `--resume <sessionId>`
(captured from the run's `stream-json` init event and persisted) — and for a *granted*
permission we add the specific tool to `--allowedTools` so the retried action goes through.
Because all state lives on disk, this survives a server restart. The MCP progress server
and the `PreToolUse` hook run as child processes of `claude -p` and report back over
Promptly's localhost **internal HTTP API** (token-guarded, `X-Promptly-Token`); uvicorn
stays the single writer of `progress.json` and owns the kill/SSE control flow.

## Lifecycle
```
pending ──start──▶ in_progress ──report_done──▶ in_review
   ▲                   │  ▲                          │
   │            ask_question │ answer          feedback│  create PR
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
Execution is **two AI calls**. First a short, **MCP-free generation call**
(`ClaudeService.plan_execution_steps`, `plan_steps.md.j2`, generation profile = repo-wide
reads, no writes) breaks the task into an ordered list of concrete steps ("research X",
"implement Y", "add tests", "run the suite"). These are seeded into `progress.steps`
(`storage.seed_steps`) **all incomplete except the first, which is set `in_progress`**, and a
`steps` SSE event is emitted so the UI shows the plan immediately. The build session that
follows is given this plan inlined in its prompt — it does **not** re-plan. (If planning
fails, the execution is marked `failed` before any worktree session starts.)

## The run loop
ExecutionManager spawns a `claude -p` build session built by
`ClaudeService.build_run_command()` (03): `cwd = worktree/`, `--output-format stream-json`,
the **execution** permissions profile compiled into `--settings`/`--permission-mode`/`--add-dir`
(09), the MCP server (`--mcp-config` + `--strict-mcp-config`) and the `PreToolUse` hook
registered, all bound to this `executionId` via env. ExecutionManager owns the subprocess
(in a registry) so it can kill it; it drains `stream-json` only to capture the `session_id`
from the init event (progress itself comes from the MCP tools, not text parsing).
- **Prompt:** rendered from `execute_task.md.j2` (09). The **task spec is inlined** (Claude
  must have it verbatim) **along with the pre-planned step list**; the project spec, sibling
  specs, `CLAUDE.md`, and source are read by path **from the worktree's own checkout** (reads
  are confined to the worktree — see Permissions). Claude works the plan one step at a time:
  as it finishes each it calls `complete_step(title)` — which marks that step `done` and
  **auto-advances the next pending step to `in_progress`** — and if the plan needs to change it
  calls `revise_steps` with the **entire** updated list (each `{title, detail?, done}`), which
  rebuilds the list (preserving ids/timestamps by title) and re-derives the active step. It
  asks via `ask_question` when blocked and calls `report_done` when finished. It may only
  **write** inside the worktree.
- **Progress writes come from the MCP tools**, not from parsing model text: each tool call
  mutates this execution's `progress.json` (via StorageService, locked atomic write) and
  publishes an event to the SSE bus. This is why MCP is preferred over Claude editing JSON.
- **Session id:** capture from the `stream-json` init event and persist to `progress.json`
  as soon as known (enables every later `--resume`).
- **Completion:** `report_done` is **guarded** — the internal endpoint first checks every step
  is `done`/`skipped`; if any remain it is **rejected** (returns `complete:false` + the list of
  remaining steps to the model, the process keeps running) so the session must finish or revise
  the plan before it can end. Once all steps are complete it records `doneSummary` and stops the
  process; on exit the run loop **commits the worktree changes once** with a generated message
  (single commit per `report_done`; subsequent feedback rounds add their own commit), sets
  `progress.status = completed`, task `status = in_review`, emits `status` SSE.
- **Failure:** non-zero exit / crash (with no recorded pause) → `progress.status = failed`,
  surface stderr; the user can retry/feedback.
- **Why exit?** The run loop distinguishes *why* a process ended via an interrupt reason set
  when we kill it: `input` (question/permission — stay `awaiting_input`, do nothing),
  `done` (finalize/commit), `cancel` (failed); a natural exit-0 with no reason also finalizes,
  a non-zero exit fails.

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
ExecutionManager keeps an in-memory `dict[execution_id -> subscribers]`. MCP tool calls and
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
4. Run loop via `run_session()` (execution permissions profile + `execute_task.md.j2`) +
   MCP-driven progress writes.
5. `PreToolUse` approval hook + `pendingPermissions` ↔ `/permission` wiring (09).
6. Answer / feedback / PR-comment resume paths.
7. Diff endpoint + PR creation.
8. Cancel/cleanup + concurrent-execution registry.
9. Tests: worktree lifecycle, MCP→progress→SSE path, permission-hook flow, resume flows
   (mock ClaudeService).

## Resolved decisions
- **Interaction model:** kill-and-resume (above), not a blocking hook/tool. Questions +
  permission requests are persisted to `progress.json`, the process is killed, and the user's
  response re-spawns it with `--resume` (+ `--allowedTools` for grants).
- **Helper ↔ Promptly channel:** localhost internal HTTP API, token-guarded. uvicorn is the
  single writer of `progress.json` and owns SSE + the kill.
- **PR tooling:** `gh` CLI (reuses the user's GitHub auth).
- **Liveness monitor + auto-resume:** in-flight runs die with the server (or if a build
  process is killed without finalizing). We track which executions have a live/starting run in
  an in-memory `_active` set (maintained synchronously, since `_procs` is only populated after
  the subprocess spawns and planning has no process). The client polls
  `POST /executions/{id}/ensure-running` **on visit and on an interval** while a run shows
  `running`; if the execution is `running` but not in `_active`, the run is dead → we
  **resume the session (`--resume`) and tell it to continue**. If there's no `session_id` to
  resume, the execution is marked `failed`. A session that's gone surfaces via the normal
  failure path (the resumed `claude --resume` exits non-zero → `_finalize` records the error →
  failed banner). We no longer fail orphaned `running` executions on startup — they're
  recovered on demand; `awaiting_input` stays paused for the user.
