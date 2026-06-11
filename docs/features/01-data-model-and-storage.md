# 01 — Data Model & Storage

**Depends on:** nothing. **Blocks:** everything.

The filesystem is the database. This doc pins down every file format so the API, the AI
prompts, and the UI all agree. Implement this as a **StorageService** module with pure,
well-tested read/write functions before any UI exists.

## 1. Project descriptor
When a project is created we capture `name` + `root`. Store a small registry so the app
can list/reopen projects without scanning the disk.

`~/.promptly/projects.json` (app-level, outside any codebase):
```json
{
  "projects": [
    { "name": "promptly", "root": "/abs/path/to/codebase", "lastOpenedAt": "ISO8601" }
  ]
}
```
The project's own dir is always `<root>/projects/<name>/`. Slugify `name` for the path.

## 2. Document/task metadata (`docs.json`, `tasks.json`)
Both files share one entry schema. They are **maps keyed by id** (not arrays) so lookups
and partial updates are O(1) and merge-friendlier.

```jsonc
// tasks/tasks.json  (docs/docs.json is identical minus task-only fields)
{
  "<id>": {
    "id": "uuid",
    "name": "Set up auth",                 // 1. display name
    "type": "task",                        // 2. "task" | "project_spec" | "doc"
    "description": "Add login + sessions", // 3. short summary
    "status": "pending",                   // 4. status enum (tasks only; docs may omit)
    "taskGroup": "Backend",                // 5. grouping label (tasks only)
    "relatedPRs": [                         // 6. optional
      { "url": "https://github.com/o/r/pull/12", "number": 12, "state": "open" }
    ],
    "dependsOn": ["<id>", "<id>"],         // 7. ids this depends on
    "custom": { "jira": "PROJ-3", "assignee": "pablo" }, // 8. arbitrary user kv
    "executionId": "<execution-id|null>",  // 9. active/last execution
    "file": "tasks/set-up-auth.md",        // relative path to the md body
    "operation": {                          // 10. in-flight AI op, else null (03/05)
      "type": "generate",                   //     "generate" | "chat" | "address"
      "status": "running",                  //     "running" | "failed"
      "startedAt": "ISO8601",
      "error": null
    },
    "createdAt": "ISO8601",
    "updatedAt": "ISO8601"
  }
}
```

### Async operations (`operation`)
AI authoring/editing is asynchronous (03/05). While a doc is being generated or edited, its
entry carries a non-null `operation`; it's `null` otherwise. This is **persisted** so a page
refresh still shows the loading state, and changes are broadcast over an operations SSE
stream (02). A **brand-new** doc gets a metadata entry with an empty body and
`operation.status=running` the instant generation starts, so it appears in the sidebar (with
a spinner) immediately; the body/metadata fill in on completion. On failure, `status` is set
to `failed` with an `error` message until the user retries.

### Status enum (canonical, used app-wide)
`pending | in_progress | in_review | blocked | done | removed`

- Store snake_case in JSON; map to display labels in the UI.
- `removed` is a soft delete: never rendered in Plan by default, hidden from most lists,
  but kept so dependency references don't dangle. Provide a "show removed" toggle.

### The project spec
`project.md` lives at the project root and has metadata too. Keep its entry in
`docs.json` with `type: "project_spec"` and `file: "project.md"`. Exactly one project_spec
should exist; the "create first doc" flow ([05](./05-design-tab.md)) creates it.

### Identity & filenames
- `id` is the only identity. Filenames are `slug(name)` and may collide → on write,
  de-dupe with `-2`, `-3` suffixes. Renaming a doc may rename the file; update `file` in
  metadata atomically.

## 3. In-file comments (highlight comments)
Comments on a doc are appended to the **end of the `.md`** inside an HTML comment so they
never render in markdown and travel with the file.

```markdown
...document body...

<!-- promptly:comments
{
  "comments": [
    {
      "id": "uuid",
      "anchor": { "quote": "exact highlighted substring", "start": 1234, "end": 1290 },
      "body": "Should this also handle refresh tokens?",
      "kind": "comment",            // "comment" | "question"
      "author": "user",
      "resolved": false,
      "createdAt": "ISO8601"
    }
  ]
}
-->
```
- Use a sentinel (`promptly:comments`) so the parser can find/replace the block
  deterministically. There is **at most one** such block, always last.
- `anchor.start/end` are character offsets into the body (the text *before* the comment
  block). `quote` is the fallback for re-anchoring if offsets drift after an edit
  (search for the quote; if not found, mark the comment "orphaned").
- When sending a doc "to be addressed by AI", we pass body + unresolved comments; on
  success the AI's revision replaces the body and we mark addressed comments `resolved`.
- `kind` is `comment` (annotation) or `question`. Interactive Q&A now happens in the doc
  **chat** (below); highlight → "Ask AI" feeds the quoted span into the chat rather than
  creating a `question` comment.

## 3b. Doc chat history
Each doc/task has a conversational chat (05) for free-form change requests and questions,
stored in a **per-entry sidecar** keyed by id so it survives renames:
`<collection>/.chats/<id>.json` (e.g. `docs/.chats/<id>.json`, `tasks/.chats/<id>.json`).

```json
{
  "entryId": "uuid",
  "sessionId": "claude-session-id-or-null",
  "messages": [
    { "id": "uuid", "role": "user", "content": "make the auth section terser",
      "createdAt": "ISO8601" },
    { "id": "uuid", "role": "assistant", "content": "Done — trimmed it.",
      "revisedBody": true, "createdAt": "ISO8601" }
  ]
}
```
- `sessionId` lets each new message **resume** the Claude session (03) so the conversation
  has memory and full repo read access.
- `revisedBody: true` flags assistant turns that changed the doc body (the body itself lives
  in the `.md`; we just note the turn edited it).
- The `.chats/` dir is committable history; keep messages append-only.

## 3c. Per-project permissions config
`<root>/projects/<name>/permissions.json` — Promptly-managed but **user-editable** — declares
what file/tool access AI operations get (whole-repo reads by default; writes constrained).
Full schema, profiles (`generation`/`execution`), and how it compiles into Claude CLI
`--settings`/`--permission-mode` live in [09](./09-prompts-and-permissions.md). StorageService
reads it (returning documented defaults when absent); the API exposes read/update (02).

## 4. Execution state
Per execution dir `executions/<execution-id>/`:

### `progress.json`
```json
{
  "executionId": "uuid",
  "taskId": "uuid",
  "sessionId": "claude-session-id-or-null",
  "status": "running | awaiting_input | completed | failed",
  "pendingQuestions": [
    { "id": "uuid", "question": "...", "answer": null, "askedAt": "ISO8601" }
  ],
  "steps": [
    { "id": "uuid", "title": "Add User model", "detail": "...",
      "status": "pending | in_progress | done | skipped",
      "startedAt": "ISO8601", "finishedAt": "ISO8601|null" }
  ],
  "createdAt": "ISO8601",
  "updatedAt": "ISO8601"
}
```

### `comments.json` (diff comments, partitioned by commit)
```json
{
  "byCommit": {
    "<commit-sha>": [
      { "id": "uuid", "file": "src/auth.py", "side": "new",
        "lineStart": 40, "lineEnd": 44, "body": "rename this", "author": "user",
        "resolved": false, "createdAt": "ISO8601" }
    ]
  }
}
```
Partitioning by commit means new commits don't invalidate old comments — they stay pinned
to the commit they were written against. See [08](./08-build-tab.md).

### `worktree/`
A git worktree created at execution start (see [07](./07-execution-engine.md)). Must be in
the root's `.gitignore`.

## 5. The StorageService (implementation)
A single module the API depends on. Functions are pure-ish (path in, data out) and never
touch the network.

Responsibilities:
- Resolve project paths (`project_dir(root, name)`, `tasks_path`, etc.).
- Read/write `docs.json` / `tasks.json` with **atomic writes** (write tmp + `os.replace`)
  and a per-file lock to avoid corruption from concurrent writes (UI + MCP callbacks).
- Parse/serialize the trailing comment block in `.md` files.
- CRUD for metadata entries, including cascade rules:
  - deleting/removing a task → set `status: removed`, leave it referenced.
  - editing `dependsOn` → reject edges that would create a cycle (validate in graph util).
- Provide a `dependency_graph()` helper returning nodes + edges for the Plan tab and for
  cycle detection.

## Implementation steps
1. Path resolver + project registry (`projects.json`) read/write.
2. Metadata read/write with atomic write + lock; schema validation (Pydantic models).
3. `.md` body + comment-block parser/serializer with round-trip tests.
4. Execution-state read/write (`progress.json`, `comments.json`).
5. Graph + cycle-detection utilities.
6. Unit tests for every format (round-trip, malformed input, dependency cycles, orphaned
   comment re-anchoring).

## Open questions
- Do we keep an append-only history of metadata changes? v1: no, rely on git.
- Offset-based anchors are brittle across heavy edits — is quote-only matching enough?
  Start with offset + quote fallback; revisit if users report drift.
