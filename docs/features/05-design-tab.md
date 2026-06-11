# 05 — Design Tab

**Depends on:** [02 API](./02-python-api-server.md), [03 Claude](./03-claude-cli-integration.md),
[04 Frontend Foundation](./04-frontend-foundation.md).

Where the user views and edits the project spec, supplemental docs, and task specs — and
where AI authors them. The user **never writes files directly**: creating a doc means
prompting AI. Manual edits to existing bodies are allowed (the editor saves via `PUT`), but
creation is always prompt-driven.

## Layout
```
┌───────────── Design ─────────────────────────────────────────┐
│ Left sidebar          │  Main view (open doc)                 │
│ ┌───────────────────┐ │  ┌──────────────────────────────────┐ │
│ │ Metadata section  │ │  │ rendered markdown / editor        │ │
│ │ (open doc's meta) │ │  │ highlight → comment popover       │ │
│ ├───────────────────┤ │  │                                   │ │
│ │ project.md        │ │  │                                   │ │
│ │ docs/             │ │  │                                   │ │
│ │  - architecture   │ │  └──────────────────────────────────┘ │
│ │ tasks/            │ │  [ Address comments with AI ] button   │
│ │  - set up auth    │ │                                        │
│ │ [ + new ]         │ │                                        │
│ └───────────────────┘ │                                        │
└───────────────────────┴───────────────────────────────────────┘
```

## Left sidebar
- **Metadata section (top):** shows the open doc's metadata (name, type, description,
  status, task group, related PRs, dependsOn, custom fields, executionId). Inline-editable;
  saves via `PUT /docs|tasks/{id}/metadata`. "Add custom value" adds a kv pair to `custom`.
  Reuses the shared `MetadataPanel` (04).
- **File tree:** `project.md` pinned at top, then `docs/`, then `tasks/`, each listing
  entries from `docs.json` / `tasks.json`. Clicking opens it in the main view. Status badge
  per task. `removed` items hidden unless a "show removed" toggle is on.
- **`+ new` button:** opens `PromptDialog` (04). User picks **type** (supplemental doc vs.
  task spec) and writes a prompt for what they want. For tasks, an optional dependency
  picker selects `dependsOn`. Submit → `POST /docs` or `POST /tasks` with the prompt → AI
  generates the body and metadata → new file appears and opens. Show a generating spinner.

## Empty state (first doc = project spec)
If the project has no `project_spec` yet, the main view shows a focused prompt: "Describe
your project — what is it and what's it for?" Submitting calls `POST /docs` with
`type=project_spec`; the backend frames it as the project-spec prompt and saves `project.md`
(see [03](./03-claude-cli-integration.md)). Only after that does the normal `+ new` flow
become available.

## Doc viewer / editor
- Render markdown (e.g. `react-markdown`). The trailing `promptly:comments` block is parsed
  out by the API and **never rendered as markdown** — comments come back as structured data.
- **Manual edit** mode: a markdown editor (CodeMirror) for hand-tweaks; save via `PUT`.
  Use optimistic-concurrency etag (02) to avoid clobbering AI revisions.
- **Highlighting:** selecting text shows a popover with "Comment" / "Ask AI a question".
  Submitting computes the anchor (`{quote, start, end}` per [01](./01-data-model-and-storage.md))
  and `POST /docs/{id}/comments`. Existing comments render as margin markers / highlights;
  clicking one shows the thread and a resolve toggle.
- Comments are visually distinct by `kind` (`comment` vs `question`).

## Address comments with AI
- A button (enabled when unresolved comments exist) → `POST /docs/{id}/address`.
- Backend sends body + unresolved comments to Claude (03) and returns a **proposed
  revision**. Show a diff/preview (old vs. proposed). On **accept**, the body is replaced
  and addressed comments are marked `resolved`; on reject, nothing changes.
- This is the doc-level analogue of task execution: AI edits the doc, user reviews.

## Wiring to other tabs
- Opening a task doc here is the target of Plan's "Open in Design" action (04 routing):
  `/p/:project/design?doc=<id>`.
- The metadata panel shows `executionId` with a link to Build when present.

## Implementation steps
1. Sidebar file tree from `useDocs()`/`useTasks()`; open-doc routing.
2. Markdown viewer + comment-data rendering (highlights/markers).
3. `PromptDialog`-driven create for docs and tasks (incl. dependency picker for tasks).
4. Empty-state project-spec flow.
5. Highlight → comment/question creation with anchoring; resolve toggle.
6. Manual editor + save with etag.
7. "Address comments" → preview → accept/reject.
8. Metadata section (reuse `MetadataPanel`) incl. custom fields.

## Open questions
- Re-anchoring comments after a large AI revision: keep by quote match, mark orphaned
  otherwise (per 01). Show orphaned comments in a separate list rather than dropping them.
- Do supplemental docs need statuses? Spec lists status as task-oriented; keep status
  optional for `doc`/`project_spec` and hide the control for them.
