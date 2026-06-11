# Promptly

A local-first web app for **designing, planning, and building software projects with AI**.
You write a project spec, break it into docs and tasks (all authored by AI from your
prompts), see them as a dependency graph, and have Claude execute tasks in isolated git
worktrees — all driven by the **Claude CLI in headless mode**.

It has three tabs:

- **Design** — view/edit the project spec, supplemental docs, and task specs. You never
  write files directly; you prompt the AI to author them, then review/comment/revise.
- **Plan** — _(coming)_ a dependency graph + Kanban board of tasks.
- **Build** — _(coming)_ run a task: Claude works in an isolated worktree while you watch
  steps, answer questions, review the diff, and open a PR.

> **Status:** features 01–05 are implemented (storage, API, AI generation, frontend shell,
> Design tab). Plan (06), Execution engine (07), and Build (08) are in progress. See
> [`docs/features/`](./docs/features/) for the full plan.

## How it works

- **Frontend:** React + TypeScript (Vite), Tailwind, React Query + Zustand, React Router.
- **Backend:** Python + FastAPI. Owns orchestration only.
- **AI:** every model call shells out to the **Claude CLI** (`claude -p …`). Promptly never
  calls the Anthropic API directly — it reuses your existing Claude Code auth/config.
- **Persistence:** the **filesystem is the database** (no DB). A project's files live at
  `<root>/projects/<name>/` inside your codebase, so they're diffable and git-friendly.

```
React SPA  ──HTTP/SSE──▶  FastAPI  ──subprocess──▶  Claude CLI (headless)
                            │
                     reads/writes project files on disk
```

## Prerequisites

- **Python** ≥ 3.12
- **Node** ≥ 20 (developed on 24) + npm
- **Claude CLI** installed and authenticated — verify with `claude --version`
  (developed against v2.1.173). All AI features require this.
- **git** (projects must live inside a git repository)

## Setup

Clone, then set up both halves:

```bash
# Backend (from the repo root)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"        # installs FastAPI, pydantic, pytest, etc.

# Frontend
cd web
npm install
cd ..
```

## Running it (development)

Run the two servers in separate terminals.

**1. Backend API** (port 8000):

```bash
.venv/bin/python -m uvicorn api.main:app --reload --port 8000
```

**2. Frontend** (port 5173, proxies `/api` → `:8000`):

```bash
cd web
npm run dev
```

Then open **http://localhost:5173**.

Interactive API docs (Swagger) are at **http://localhost:8000/api-docs**.

### First run

1. Click **New project**. Give it a name and the **absolute path to an existing git repo**
   (the codebase you're working on). Promptly creates `<root>/projects/<name>/`.
2. In **Design**, describe your project — the AI drafts `project.md`.
3. Add docs/tasks with **+ Doc** / **+ Task** (tasks can declare dependencies).
4. Edit, highlight text to comment or ask the AI a question, then **Address comments with AI**
   to have it revise the document for your review.

## Project layout

```
promptly/
├─ api/                     # FastAPI backend
│  ├─ main.py               # app + routers + error envelope
│  ├─ deps.py               # service singletons, active-project resolution
│  ├─ models.py, schemas.py # on-disk models / HTTP schemas
│  ├─ routers/              # projects, docs, tasks, metadata, executions
│  ├─ services/             # claude.py (CLI), execution.py (engine + SSE bus)
│  ├─ storage/              # filesystem-as-database (the StorageService)
│  ├─ prompts/              # versioned prompt templates
│  └─ tests/                # pytest suite
├─ web/                     # React frontend (Vite)
│  └─ src/
│     ├─ lib/               # api client, react-query hooks, sse, types
│     ├─ store/             # zustand UI state
│     ├─ components/        # shared primitives
│     └─ features/          # projects, design, plan, build
└─ docs/features/           # the implementation plan (00–08)
```

A Promptly **project** on disk:

```
<your-codebase>/
└─ projects/<name>/
   ├─ project.md            # the spec (+ trailing comments as JSON in an HTML comment)
   ├─ docs/{docs.json, *.md}
   ├─ tasks/{tasks.json, *.md}
   └─ executions/<id>/      # per-run state + git worktree (gitignored)  [feature 07]
```

## Tests

```bash
# Backend
.venv/bin/python -m pytest

# Backend incl. a real Claude CLI smoke test (makes a live call; needs auth)
PROMPTLY_CLI_TEST=1 .venv/bin/python -m pytest

# Frontend typecheck + build
cd web && npm run build
```

## Configuration

- `PROMPTLY_HOME` — where the app-level project registry (`projects.json`) lives.
  Defaults to `~/.promptly`. Handy for isolating test/dev data.
