# 05 — Design Tab

**Depends on:** [02 API](./02-python-api-server.md), [03 Claude](./03-claude-cli-integration.md),
[04 Frontend Foundation](./04-frontend-foundation.md).

Where the user views and edits the project spec, supplemental docs, and task specs — and
where AI authors them. The user **never writes files directly**: creating a doc means
prompting AI. Manual edits to existing bodies are allowed (the editor saves via `PUT`), but
creation is always prompt-driven.

> **AI authoring is asynchronous** (user feedback). Generating or editing a doc runs as a
> background **operation** (01/03): the request returns immediately and the user can keep
> working. The Design tab reflects in-flight operations with **loading states** (below) and
> updates live via the operations SSE stream (02/04).

## Layout
```
┌───────────── Design ─────────────────────────────────────────────────┐
│ Left sidebar          │  Main view (open doc)        │ Right panel    │
│ ┌───────────────────┐ │  ┌──────────────────────────┐│ [Chat|Comments]│
│ │ Metadata section  │ │  │ rendered markdown / editor ││  ┌───────────┐ │
│ │ (open doc's meta) │ │  │ highlight → comment / ask  ││  │ chat msgs │ │
│ ├───────────────────┤ │  │                            ││  │   ...     │ │
│ │ project.md      ⟳ │ │  │                            ││  ├───────────┤ │
│ │ docs/             │ │  └──────────────────────────┘│  │ [type…]   │ │
│ │  - architecture   │ │  [ Address comments with AI ] │  └───────────┘ │
│ │ tasks/            │ │                                │                │
│ │  - set up auth    │ │                                │                │
│ │ [ + Doc ] [ +Task]│ │                                │                │
│ └───────────────────┘ │                                │                │
└───────────────────────┴────────────────────────────────┴───────────────┘
```
(`⟳` = a doc with an operation in progress.)

## Loading states (async authoring)
A doc/task carries an `operation` ({type, status} — 01) while AI is generating or editing it:
- **Sidebar:** show a small **loading spinner beside the name** of any doc with a running
  operation. The user can navigate elsewhere while it runs.
- **Brand-new doc** (created by a prompt): a placeholder entry appears in the sidebar
  immediately (with spinner). If selected, the main view shows a **blank loading state**
  (the body doesn't exist yet).
- **Existing doc being edited** (chat edit / address): if selected, render the current doc
  with a **banner** ("Changes in progress…") and **disable editing/commenting** until the
  operation completes.
- On completion the SSE event clears the operation; the body/metadata refresh in place. On
  failure, surface the error and clear the operation so the user can retry.

## Left sidebar
- **Metadata section (top):** shows the open doc's metadata (name, type, description,
  status, task group, related PRs, dependsOn, custom fields, executionId). Inline-editable;
  saves via `PUT /docs|tasks/{id}/metadata`. "Add custom value" adds a kv pair to `custom`.
  Reuses the shared `MetadataPanel` (04).
- **File tree:** `project.md` pinned at top, then `docs/`, then `tasks/`, each listing
  entries from `docs.json` / `tasks.json`. Clicking opens it in the main view. Status badge
  per task. `removed` items hidden unless a "show removed" toggle is on.
- **`+ Doc` / `+ Task` buttons:** open `PromptDialog` (04) with the prompt for what to
  create; for tasks, an optional dependency picker selects `dependsOn`. Submit → `POST /docs`
  or `POST /tasks` → the API returns immediately with a placeholder entry (operation running)
  → it appears in the sidebar with a spinner and is selected → body/metadata fill in when the
  background operation completes (no blocking).
- **`Import` button:** import existing docs/tasks — a dialog to pick the **type** (Document or
  Task), then **upload one or more `.md` files** (each becomes its own entry) or **paste** a
  single document with a name. Each `POST /docs/import` writes the **body verbatim**
  (synchronous) and routes by type to the right collection (docs vs. tasks). It then runs a
  **background AI op to fill metadata** (description; `taskGroup` for tasks) — the body is never
  modified — so the entry shows immediately with a spinner that clears when metadata arrives
  (via the operations SSE, like generation). Available anytime in Design; the **project spec**
  import (single, fixed type) is offered in the empty state (below).
- **`Generate tasks from spec` button:** shown in the tasks section **when the project has no
  tasks yet** (and a `project_spec` exists). Calls `POST /tasks/generate-from-spec` (02/03):
  the AI breaks the spec into tasks, which appear as placeholders (spinners) and fill in
  asynchronously. The same action is offered in the Plan blank slate (06).

## Empty state (first doc = project spec)
If the project has no `project_spec` yet, the main view shows a focused prompt: "Describe
your project — what is it and what's it for?" Submitting calls `POST /docs` with
`type=project_spec`; the backend frames it as the project-spec prompt and saves `project.md`
(see [03](./03-claude-cli-integration.md)). The empty state also offers **Import project
spec** (paste/upload an existing `project.md` via `POST /docs/import`) for users who already
have one. Only after a spec exists does the normal create/import flow become available.

## Doc viewer / editor
- Render markdown (`react-markdown`). The trailing `promptly:comments` block is parsed out by
  the API and **never rendered as markdown** — comments come back as structured data.
- **Mode toggle is a floating action button** (no toolbar View/Edit tabs): a **pencil** FAB
  enters edit mode; while editing it becomes a **checkmark** that saves and returns to view
  (hidden while an operation is in progress).
- **Manual edit** mode — **Obsidian-style live preview** (`LiveEditor`): the doc stays
  rendered as Markdown, and only the **block the cursor is in** turns into a raw-text box;
  clicking another block renders the previous one and edits the new one, clicking outside
  renders all. View mode stays pure rendered Markdown. The body is split into contiguous
  blocks (blank-line runs + fenced code preserved) so offsets are exact: a selection inside a
  block maps to global `{quote, start, end}` comment anchors
  ([01](./01-data-model-and-storage.md)). Save via `PUT`. Disabled while an operation is in
  progress (loading states, above).
- **Highlighting:** selecting text offers **"Comment"** (an annotation) or **"Ask AI"**
  (sends the quoted span into the doc **Chat** for an immediate answer — see right panel).
  A comment computes the anchor and `POST /docs|tasks/{id}/comments`. Existing comments render
  as markers/highlights; clicking shows the note and a resolve toggle.

## Right panel — Chat / Comments toggle
A toggle at the top of the right panel switches between **Chat** and **Comments** (user
feedback):

- **Chat** — a conversational box to **request general changes** to the doc or **ask
  questions** about it. Messages are sent **one at a time, each getting its own response**
  (not batched). Backed by a resumable Claude session with full repo read access (03). A
  change request revises the doc body (the AI is its author); the doc shows the in-progress
  banner while the turn runs, then refreshes. Chat history persists per doc (01). `POST
  /docs|tasks/{id}/chat {message}` → background operation → SSE updates.
- **Comments** — the list of highlight comments (annotations). Each shows its quoted anchor,
  body, and a resolve toggle; orphaned comments (after a big revision) live in a separate
  list (01).

## Address comments with AI
- A button (enabled when unresolved comments exist) → `POST /docs|tasks/{id}/address`.
- Runs as a background operation; the backend sends body + unresolved comments to Claude (03)
  and returns a **proposed revision** for preview (old vs. proposed). On **accept**, the body
  is replaced and addressed comments are marked `resolved`; on reject, nothing changes.
- This is the batch analogue of Chat: many comments at once, with a review step. (Chat is for
  single, conversational requests.)

## Wiring to other tabs
- Opening a task doc here is the target of Plan's "Open in Design" action (04 routing):
  `/p/:project/design?doc=<id>`.
- The metadata panel shows `executionId` with a link to Build when present.

## Implementation steps
1. Sidebar file tree from `useDocs()`/`useTasks()`; open-doc routing.
2. Markdown viewer + comment-data rendering (highlights/markers).
3. `PromptDialog`-driven create for docs and tasks (incl. dependency picker for tasks) — as
   **async operations** returning placeholders.
4. Empty-state project-spec flow.
5. **Operations SSE wiring + loading states** (sidebar spinner, blank-new, in-progress banner
   that disables edits).
6. Highlight → comment creation with anchoring; resolve toggle; orphaned list.
7. Right-panel **Chat/Comments toggle**; Chat (send one message → response; body revisions).
8. "Address comments" → preview → accept/reject.
9. Metadata section (reuse `MetadataPanel`) incl. custom fields.

> **Build status:** steps 1–4, 6, 8, 9 shipped in the first 05 pass (synchronous). This
> revision adds async operations + loading states (3, 5), Chat + the Chat/Comments toggle (7),
> and moves "Ask AI" from a comment kind to the Chat. These are pending re-implementation.

## Open questions
- Re-anchoring comments after a large AI revision: keep by quote match, mark orphaned
  otherwise (per 01). Show orphaned comments in a separate list rather than dropping them.
- Do supplemental docs need statuses? Spec lists status as task-oriented; keep status
  optional for `doc`/`project_spec` and hide the control for them.
- Should a chat change-request show a preview/accept step like "Address comments," or apply
  directly (since the AI authors the doc)? Lean **apply directly** (it's editable/revertable),
  but revisit if users want a gate.
