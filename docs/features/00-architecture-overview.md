# 00 — Architecture Overview

> Reference doc. No code ships from here; it sets shared vocabulary and decisions the
> feature docs build on.

## Goal
A local-first web app that helps a user **Design** (write specs/docs/task definitions),
**Plan** (see tasks as a dependency graph / Kanban board), and **Build** (have Claude
execute tasks in isolated git worktrees and review the results).

## Tech stack
- **Frontend:** React + TypeScript (Vite). State via Zustand or React Query for server
  state; minimal global UI state. Graph rendering: see [06](./06-plan-tab.md) for the
  React Flow vs. custom-canvas decision.
- **Backend:** Python (**FastAPI**). FastAPI gives us typed request/response models,
  async subprocess handling for the Claude CLI, and native **SSE** for live progress.
- **AI:** the **Claude CLI in headless mode** (`claude -p ...`), spawned as a subprocess
  by the backend. We never call the Anthropic HTTP API directly — all model access is
  mediated by the CLI so the user's existing Claude Code auth/config is reused. AI ops get
  **read access to the whole repo** for context (constrained by a per-project permissions
  config) and are *told to read* `CLAUDE.md`/specs/tasks/source before writing ([09](./09-prompts-and-permissions.md)).
- **Prompts:** Jinja2 templates in a top-level **`prompts/`** dir (outside the app code) so
  they're easy to edit (09).
- **Async authoring:** doc/task generation and edits run as **background operations** with
  live status over SSE, so the UI never blocks (01/02/05).
- **Persistence:** the filesystem. There is **no database** in v1 — the project's files
  (`project.md`, `*.md`, `*.json`) are the source of truth. This keeps everything
  diffable, git-friendly, and editable outside the app.

## Two filesystem locations (don't conflate them)
1. **The root** — the user's actual codebase. Git lives here; worktrees and `.gitignore`
   edits happen here.
2. **The Promptly project dir** — `<root>/projects/<project-name>/`. All Promptly-managed
   docs, task metadata, and execution state live here. It sits *inside* the root so it can
   be committed alongside the code (the `executions/.../worktree/` dirs are gitignored).

### On-disk layout of a project
```
promptly-app/                    # this repo
└─ prompts/                      # Jinja2 prompt templates, editable (09)

<root>/                          # user's codebase, a git repo
├─ .gitignore                    # we ensure it ignores the worktrees
└─ projects/
   └─ <project-name>/
      ├─ project.md              # main spec (+ trailing comments JSON)
      ├─ permissions.json        # per-project AI permissions, user-editable (09)
      ├─ docs/
      │  ├─ docs.json            # metadata for all docs (incl. async `operation`)
      │  ├─ <doc-slug>.md
      │  └─ .chats/<id>.json     # per-doc chat history + session id (01/05)
      ├─ tasks/
      │  ├─ tasks.json           # metadata for all tasks
      │  ├─ <task-slug>.md
      │  └─ .chats/<id>.json
      └─ executions/
         └─ <execution-id>/
            ├─ progress.json     # steps, pending questions/permissions, session id
            ├─ comments.json     # diff comments, partitioned by commit
            └─ worktree/         # git worktree for this execution (gitignored)
```
Full schemas: [01 — Data Model & Storage](./01-data-model-and-storage.md).

## Component map
```
┌─────────────────────────── React SPA ───────────────────────────┐
│  App shell (project picker, tab nav)                             │
│  Design tab   │   Plan tab   │   Build tab                       │
│        │            │              │                             │
│        └──── API client (fetch + SSE) ──────────────────────────┘
                         │ HTTP / SSE
┌────────────────────── FastAPI server ───────────────────────────┐
│  Routers: projects, docs, tasks, metadata, executions           │
│  StorageService  (reads/writes the files above)                 │
│  ClaudeService   (spawns `claude -p`, parses stream-json)        │
│  ExecutionManager(worktrees, run loop, SSE broadcast)           │
│  MCP tool server (Claude calls back to update progress)         │ ← see 03 / 07
└──────────────────────────────────────────────────────────────────┘
                         │ subprocess
                   Claude CLI (headless)
```

## Key flows (one-liners; details in feature docs)
- **Generate a doc:** user prompt → `POST /docs` returns a placeholder (operation running) →
  background ClaudeService run reads the repo for context → writes `<slug>.md` + metadata →
  operation cleared, SSE event → UI loading state resolves.
- **Chat with a doc:** `POST .../chat {message}` → resumes the doc's Claude session → may
  revise the body → live via the operations stream.
- **Edit/address comments:** highlight comments on the `.md` → `POST .../address` → Claude
  rewrites honoring comments → preview → accept/save.
- **Plan view:** reads `tasks.json`, builds the dependency graph, renders graph/board.
- **Execute a task:** `POST /executions` → ExecutionManager makes a worktree, spawns
  Claude with the MCP tools, streams steps/questions into `progress.json`, broadcasts
  over SSE → status `pending → in_progress → in_review`.

## Non-goals for v1
- No hosted/multi-user deployment, no auth.
- No real-time multi-client collaboration (single user, but files stay merge-friendly).
- No direct Anthropic API usage (CLI only).
