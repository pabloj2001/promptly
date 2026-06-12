# 08 — Build Tab

**Depends on:** [04 Frontend Foundation](./04-frontend-foundation.md),
[07 Execution Engine](./07-execution-engine.md) (and its endpoints in
[02](./02-python-api-server.md)).

Where the user runs tasks and watches/steers AI as it builds them. Left sidebar of tasks by
status; main view toggles between **Info** (run/answer/feedback/PR) and **Diff** (browse
changes + comment on them).

## Layout
```
┌───────────── Build ──────────────────────────────────────────┐
│ Left sidebar         │  Main view: [ Info | Diff ] toggle     │
│ ▼ In progress / review│  ┌───────────────────────────────────┐ │
│   - set up auth      │  │ (Info or Diff for selected task)   │ │
│ ▸ Blocked            │  │                                    │ │
│ ▸ Pending            │  │                                    │ │
│ ▸ Done               │  └───────────────────────────────────┘ │
└──────────────────────┴────────────────────────────────────────┘
```

## Left sidebar — collapsible status sections
Order and default state per spec:
1. **In progress + In review** — combined, **open by default**.
2. **Blocked** — collapsed by default.
3. **Pending** — collapsed by default.
4. **Done** — collapsed by default.
(`removed` not shown.) Each row: task name + status badge + (if running) a live activity
hint. Selecting a task loads it into the main view and updates `selectedTaskId` (shared with
Plan via the ui store, 04). Sourced from `useTaskGraph()`/task list, grouped by status.

## Info view — depends on the selected task's status
**Pending** → a **Begin execution** button. Click → `POST /executions {taskId}` (07): creates
the worktree + starts the run, task flips to `in_progress`, view switches to the running UI.

**In progress** → live execution UI, driven by `useExecutionStream(executionId)` (SSE, 04):
- Task metadata header (name, group, deps).
- **Steps:** the `steps` array from `progress.json`, each with status
  (pending/in_progress/done/skipped). The plan is seeded up front by the planning phase (07)
  — shown as "Planning steps…" until it arrives — then updates live as MCP `complete_step` /
  `revise_steps` events advance it.
- **Clarifying questions (conversational):** questions surface and are answered **one at a
  time** like a chat (user feedback) — each `pendingQuestions` entry renders with an answer
  box → `POST /executions/{id}/answer` → resumes Claude (07), who may then ask the next. Not
  a batch form.
- **Permission requests:** when `pendingPermissions` is non-empty (also `awaiting_input`),
  render each flagged out-of-scope action (the tool + what it wants to do) with **Allow** /
  **Deny** buttons → `POST /executions/{id}/permission` → the waiting `PreToolUse` hook reads
  the decision and returns it to the CLI, and Claude resumes (07/09). Execution runs
  unattended within the worktree; only out-of-scope actions surface here. Driven by the SSE
  `permission` event.
- When Claude calls `report_done`, status → `in_review` and the view updates.

**In review** → review actions:
- **Send feedback** → `POST /executions/{id}/feedback` → task back to `in_progress`, Claude
  resumes (07).
- **Create PR** → `POST /executions/{id}/pr` → records PR in `relatedPRs`; show the link.
- **Review PR comments** → pulls PR comments and resumes Claude as feedback (back to
  `in_progress`).

**Done** → read-only summary (final steps, PR link, diff still browsable).

## Diff view — browse changes + comment
Toggle at top of the main view. Uses `GET /executions/{id}/diff` (07): list of changed files
+ per-file unified/side-by-side diff + current commit sha.
- File list (left of the diff or a dropdown) → select a file → **side-by-side git diff**
  (use a diff renderer, e.g. `react-diff-viewer` or Monaco diff editor).
- **Comment on changes:** select line(s) → comment popover → `POST /executions/{id}/comments`
  with `{file, side, lineStart, lineEnd, body}`. Comments are stored **partitioned by the
  current commit sha** in `comments.json` (01/07), so a later commit doesn't lose them —
  show comments for the commit they were written against, with older-commit comments
  collapsible.
- Resolve toggle per comment. These diff comments feed the "review PR comments"/feedback
  loop conceptually but are Promptly-local (distinct from GitHub PR comments).

## View toggle
Info ⇄ Diff at the top of the main view, per selected task. Diff is available whenever an
execution exists (in_progress onward); Info is always available.

## Cross-tab
- Plan's "Execute" action routes here with the task selected (04). If the task is `pending`,
  show Begin execution; otherwise show its live/in-review/done state directly.
- Selecting a task here keeps it selected when the user switches to Plan.

## Implementation steps
1. Sidebar with collapsible status sections (defaults per spec) + selection.
2. Info view routing by status; **Begin execution** (pending).
3. Live in-progress UI wired to `useExecutionStream` (steps + questions/answer +
   permission requests/allow-deny).
4. In-review actions (feedback / create PR / review PR comments).
5. Diff view: file list + side-by-side diff renderer.
6. Diff comments with per-commit partitioning + resolve.
7. Info/Diff toggle; done-state read-only view.

## Open questions
- Show raw Claude tool/output log in addition to the structured steps? Optional "activity
  log" panel fed by SSE events beyond steps — nice-to-have, not required.
- Side-by-side diff for large files/renames — pick a renderer that handles big diffs and
  binary/rename cases gracefully.
