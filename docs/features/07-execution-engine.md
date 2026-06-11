# 07 — Execution Engine

**Depends on:** [01](./01-data-model-and-storage.md), [02](./02-python-api-server.md),
[03 Claude CLI](./03-claude-cli-integration.md), [09 Prompts & Permissions](./09-prompts-and-permissions.md).
**Blocks:** [08 Build Tab](./08-build-tab.md).

The backend that runs a task: creates an isolated git worktree, spawns a stateful Claude
session that builds the task and reports progress via MCP tools, persists everything to
`executions/<execution-id>/`, and broadcasts live updates over SSE. This is the most complex
backend piece — build it after the CLI wrapper (03) works for one-shot generation.

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
2. **Worktree:** create a branch (`promptly/<task-slug>-<short-id>`) and a worktree at
   `executions/<id>/worktree/` from the root repo:
   `git -C <root> worktree add -b <branch> <execdir>/worktree HEAD`.
3. **Gitignore:** ensure the root `.gitignore` ignores
   `projects/*/executions/*/worktree/` (idempotent — only append if missing). Done once at
   project creation (02) and re-checked here.
4. Write initial `progress.json` (`status: running`, empty steps/questions, `sessionId: null`).
5. Link both ways: set `task.executionId = id` and `task.status = in_progress`;
   `progress.taskId = id`.
6. Kick off the **run loop** (background task) and return `executionId` immediately so the
   UI can subscribe to the stream.

## The run loop
Uses `ClaudeService.run_session()` (03) with `cwd = worktree/`, the **execution** permissions
profile compiled into `--settings`/`--permission-mode`/`--add-dir` (09), the MCP server
registered and bound to this `executionId`, and an `on_event` callback.
- **Prompt:** rendered from `execute_task.md.j2` (09). Claude is told to **read first** —
  the task spec, the project spec, its dependencies' specs, `CLAUDE.md`, and the relevant
  source (it has whole-repo read access via the execution profile) — then plan via
  `plan_steps`, keep steps updated via `update_step`/`add_step`, ask via `ask_question` when
  blocked, and call `report_done` when finished. It may only **write** inside the worktree.
- **Progress writes come from the MCP tools**, not from parsing model text: each tool call
  mutates this execution's `progress.json` (via StorageService, locked atomic write) and
  publishes an event to the SSE bus. This is why MCP is preferred over Claude editing JSON.
- **Session id:** capture from the stream and persist to `progress.json` as soon as known.
- **Completion:** `report_done` → **commit the worktree changes once** with a generated
  message (single commit per `report_done`; subsequent feedback rounds add their own commit),
  set `progress.status = completed`, task `status = in_review`, emit `status` SSE.
- **Failure:** non-zero exit / crash → `progress.status = failed`, surface error; leave task
  `in_progress` with an error flag so the user can retry/feedback.

## Mid-run interactions (resume the session)
All use `--resume <sessionId>` (03):
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
Claude runs **unattended by default** but **writes/executes only within the worktree**, while
it may **read the whole repo** for context.
- **Read the repo:** reads need no approval; with `cwd = worktree/` plus `--add-dir <root>`
  Claude can consult the live project docs (spec, sibling tasks/docs) and the rest of the
  codebase. It reports progress via the MCP tools (03); it does not edit docs/metadata.
- **Write/exec scoped to the worktree:** the execution profile uses `permissionMode:
  acceptEdits` (auto-accept edits in the working dir) plus deny rules for writes/exec outside
  the worktree. The worktree isolates all changes from the user's tree until a PR.
- **Flagged requests go back to the user — via a `PreToolUse` hook, not an MCP tool.** This
  CLI has **no `--permission-prompt-tool`** (verified, v2.1.173). Instead the settings we pass
  register a **`PreToolUse` hook** (09): when Claude attempts something out of scope (write/exec
  outside the worktree, a tool not on the allowlist), the hook records a **pending permission
  request**, signals Promptly, and **blocks** (waiting) until the user decides — then returns
  allow/deny to the CLI.
  - Add `pendingPermissions: [{ id, tool, request, decision: null, askedAt }]` to
    `progress.json`; the hook sets `progress.status = awaiting_input` and emits an SSE
    `permission` event. `POST /executions/{id}/permission {requestId, decision}` records the
    answer; the waiting hook reads it and returns the decision to the CLI; status resumes
    `running`. (The hook ↔ Promptly channel can be the Promptly HTTP API or a small file the
    hook polls under the execution dir — pick the simpler at implementation time.)
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

## Open questions
- PR tooling: require `gh` CLI vs. a GitHub token. `gh` reuses the user's auth — prefer it.
- What happens to in-flight executions if the server restarts? v1: mark orphaned running
  executions `failed` on startup (the subprocess died with the server); user retries.
