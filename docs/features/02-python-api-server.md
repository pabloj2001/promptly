# 02 — Python API Server

**Depends on:** [01 Data Model & Storage](./01-data-model-and-storage.md).
**Blocks:** all frontend tabs, [03](./03-claude-cli-integration.md), [07](./07-execution-engine.md).

A FastAPI app exposing CRUD over projects/docs/tasks/metadata plus SSE streams for live
execution progress. It owns no business logic beyond orchestration — storage logic lives
in StorageService (01), AI logic in ClaudeService (03), execution in ExecutionManager (07).

## App structure
```
api/
├─ main.py                # FastAPI app, CORS, router registration
├─ deps.py               # active-project resolution, service singletons
├─ models.py             # Pydantic request/response schemas (mirror 01)
├─ routers/
│  ├─ projects.py
│  ├─ docs.py
│  ├─ tasks.py
│  ├─ metadata.py
│  └─ executions.py
└─ services/
   ├─ storage.py          # from 01
   ├─ claude.py           # from 03
   └─ execution.py        # from 07
```

## Active project
Most routes operate on the active project. Two viable patterns:
- **Header/param:** every request carries `?project=<name>` (stateless, multi-project ready).
- **Session state:** `POST /projects/open` sets a server-side active project.

Recommend **param-based** (`project` query/path) so nothing is hidden in server state and
multi-project comes free. The frontend stores the active project name and attaches it.

## Endpoints

### Projects
- `GET  /projects` → registry list (`projects.json`).
- `POST /projects` → `{ name, root }`. Validates root exists & is a git repo, creates
  `<root>/projects/<name>/` skeleton (empty `docs.json`, `tasks.json`, `executions/`),
  ensures `.gitignore` ignores `projects/*/executions/*/worktree/`. Returns descriptor.
  Does **not** create `project.md` — that's the first Design action.
- `GET  /projects/{name}` → descriptor + whether a project_spec exists yet.
- `DELETE /projects/{name}` → unregister (optionally leave files on disk).

### Docs  (`type` in {project_spec, doc})
AI authoring/editing runs **asynchronously** (03/05): the create/chat/address routes return
immediately with the entry (its `operation` running) and do the Claude work in a background
task, publishing to the operations stream on completion.
- `GET  /docs?project=` → list metadata from `docs.json`.
- `GET  /docs/{id}?project=` → metadata + parsed body + parsed comments.
- `POST /docs?project=` → **prompt-driven create** `{ prompt, type, name?, dependsOn? }`.
  Creates a placeholder entry (`operation: generate/running`, empty body) and returns **202**
  immediately; a background task generates body+metadata, then clears the operation. Returns
  the placeholder entry.
- `PUT  /docs/{id}?project=` → save edited body and/or metadata (manual edits; synchronous).
- `POST /docs/{id}/chat` `{ message }` → append a user chat message and start a background
  chat turn (resumes the doc's Claude session); may revise the body. Returns the user message.
- `GET  /docs/{id}/chat` → the chat history (`.chats/<id>.json`, 01).
- `POST /docs/{id}/comments` → add a highlight comment `{ anchor, body, kind }`.
- `PUT  /docs/{id}/comments/{cid}` → edit/resolve a comment.
- `POST /docs/{id}/address` → background revise to address unresolved comments; the
  completion event carries the proposed revision (frontend previews/accepts).
- `DELETE /docs/{id}` → soft-remove.

### Tasks  (`type` = task)
Same shape as docs (incl. async create/chat/address + `/chat` history), against `tasks.json`,
plus:
- `GET  /tasks/graph?project=` → `{ nodes, edges }` for the Plan tab (excludes `removed`
  unless `?includeRemoved=true`).
- `PUT  /tasks/{id}/status` → status change (used by Kanban drag + side panel). Validates
  legal transitions where it matters (e.g. can't go `done` while an execution is running).
- Task create (`POST /tasks`) takes `{ prompt, dependsOn?, taskGroup? }` and generates the
  task spec `.md` via Claude, same as docs.

### Operations stream
- `GET /operations/stream?project=` → **SSE** of doc/task operation events so the Design tab
  shows live loading states (01/05): `event: operation  data: {entryId, type, status, error?}`.
  Backed by an in-memory per-project pub/sub (same pattern as the execution bus).

### Metadata / custom fields
- `PUT  /tasks/{id}/metadata` and `/docs/{id}/metadata` → patch any metadata field,
  including the `custom` map (add/edit/delete custom kv pairs from the Design metadata
  panel and the Plan side panel).

### Permissions config  (per-project; see [09](./09-prompts-and-permissions.md))
- `GET  /permissions?project=` → the project's `permissions.json` (or defaults if absent).
- `PUT  /permissions?project=` → replace it (the user-editable allow/deny/dirs profiles).

### Executions  (detailed in [07](./07-execution-engine.md))
- `POST /executions?project=` `{ taskId }` → start an execution. Creates worktree, sets
  `task.executionId` + `task.status=in_progress`, kicks off the run loop. Returns execution id.
- `GET  /executions/{id}` → `progress.json`.
- `GET  /executions/{id}/stream` → **SSE** of progress events (steps, questions, status).
- `POST /executions/{id}/answer` `{ questionId, answer }` → resume Claude with the answer.
- `POST /executions/{id}/permission` `{ requestId, decision }` → Allow/Deny a flagged
  out-of-scope action; returns the decision to the waiting CLI and resumes.
- `POST /executions/{id}/feedback` `{ message }` → in_review → in_progress with feedback.
- `POST /executions/{id}/pr` → create a PR from the worktree branch; record in `relatedPRs`.
- `GET  /executions/{id}/diff` → changed files + per-file diff (vs. base), current commit sha.
- `GET/POST/PUT /executions/{id}/comments` → diff comments (`comments.json`).

## SSE
Use FastAPI `StreamingResponse` / `sse-starlette`. ExecutionManager (07) maintains an
in-memory pub/sub keyed by execution id; the SSE endpoint subscribes and forwards events:
```
event: step        data: {step}
event: question    data: {question}
event: permission  data: {permissionRequest}
event: status      data: {"status": "in_review"}
```
On (re)connect, first replay current `progress.json` so a refresh re-syncs, then stream live.

## Cross-cutting
- **Validation:** Pydantic models mirror 01 schemas; reject unknown status values, cyclic
  `dependsOn`, and writes to non-existent ids.
- **Errors:** consistent `{ "error": { "code", "message" } }`; 409 for illegal state
  transitions, 422 for validation.
- **Concurrency:** all metadata writes go through StorageService's locked atomic write so
  UI edits and MCP callbacks (03/07) don't clobber each other.
- **CORS:** allow the Vite dev origin in dev.

## Implementation steps
1. App skeleton, CORS, Pydantic models, project param dependency.
2. Projects router (+ skeleton creation + `.gitignore` handling).
3. Docs & tasks CRUD (manual paths first; prompt-driven create stubbed until 03).
4. Metadata/custom-field patch routes.
5. `/tasks/graph` endpoint.
6. SSE plumbing + execution routes (stubbed until 07).
7. pytest coverage for routers (happy path + validation/cycle/transition errors).

## Open questions
- Optimistic concurrency: include `updatedAt`/etag on writes to detect stale UI saves?
  Recommended for the doc editor to avoid lost manual edits.
