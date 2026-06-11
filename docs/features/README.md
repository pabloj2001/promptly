# Promptly — Implementation Plan

Promptly is a web app for designing, planning, and building software projects with AI.
It has a **React** frontend and a **Python** API server, and it drives all AI work by
shelling out to the **Claude CLI in headless mode**.

This folder breaks the build into major features. Each doc is self-contained: scope,
data shapes, endpoints/components, implementation steps, and open questions. Docs are
numbered in roughly the order you'd build them, but read the dependency graph below.

## Feature docs

| # | Doc | What it covers |
|---|-----|----------------|
| 00 | [Architecture Overview](./00-architecture-overview.md) | Tech stack, repo layout, on-disk project layout, how the pieces talk |
| 01 | [Data Model & Storage](./01-data-model-and-storage.md) | `project.md`, `docs/`, `tasks/`, metadata JSON, in-file comment format, executions layout |
| 02 | [Python API Server](./02-python-api-server.md) | REST + SSE endpoints, project/doc/task/metadata CRUD, the storage service |
| 03 | [Claude CLI Integration](./03-claude-cli-integration.md) | Headless invocation, sessions, async doc/chat generation, the MCP tool server Claude calls back into |
| 04 | [Frontend Foundation](./04-frontend-foundation.md) | App shell, routing/tabs, project picker/creation, shared state & API client, SSE helpers |
| 05 | [Design Tab](./05-design-tab.md) | Doc sidebar, editor/viewer, create-via-prompt, async loading states, chat + comments, metadata |
| 06 | [Plan Tab](./06-plan-tab.md) | Dependency graph canvas, group containers, hover highlighting, Kanban board, task side panel |
| 07 | [Execution Engine](./07-execution-engine.md) | Worktrees, `progress.json`, the run loop, how Claude reports steps/questions |
| 08 | [Build Tab](./08-build-tab.md) | Task sidebar, Info view (start/answer/feedback/PR), Diff view + diff comments |
| 09 | [Prompts & Permissions](./09-prompts-and-permissions.md) | Editable Jinja2 prompt templates; per-project read/write permissions config; execution approval hook |

## Dependency graph

```
00 Architecture (reference, no code)
        │
01 Data Model & Storage ──────────────┐
        │                             │
02 API Server ── 03 Claude CLI ───────┤
        │            │   ╲            │
        │            │  09 Prompts & Permissions (cross-cutting: 03 + 07)
04 Frontend Foundation                │
   ├── 05 Design Tab                  │
   ├── 06 Plan Tab                    │
   └── 08 Build Tab ◄── 07 Execution Engine
```

Build order that keeps you always-runnable:
1. **01 + 02** — storage layer and CRUD API. Verify with curl / pytest.
2. **03** — Claude doc generation (no execution yet). Verify by generating a `project.md`.
3. **04** — app shell + project creation, wired to 02.
4. **05** — Design tab (the most self-contained tab; exercises docs/tasks/metadata/comments).
5. **06** — Plan tab (read-mostly over the same task data + status edits).
6. **07** — Execution engine (the hardest backend piece; worktrees + live progress).
7. **08** — Build tab on top of 07.

## Conventions used in these docs
- **Status enum** everywhere: `pending | in_progress | in_review | blocked | done | removed`.
- IDs are UUIDv4 strings. Filenames are slugs derived from `name`, never used as identity.
- "The project" = a Promptly-managed project living at `<root>/projects/<project-name>/`.
- "The root" = the user's target codebase (where worktrees and git live).

## Cross-cutting open questions (decide early)
- **Single vs. multi project at runtime.** Assume one "active project" at a time in v1; the
  API still keys everything by project path so multi-project is additive later.
- **Auth / multi-user.** Out of scope for v1 (local-first, single user). Don't bake in
  assumptions that block it (keep `author` fields on comments).
- **How Claude writes back state.** Strong recommendation: an **MCP server** (see 03/07) so
  Claude calls typed tools instead of editing JSON. Falling back to "Claude edits files" is a
  documented but discouraged alternative.
