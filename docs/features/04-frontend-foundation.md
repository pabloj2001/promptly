# 04 — Frontend Foundation

**Depends on:** [02 API Server](./02-python-api-server.md).
**Blocks:** [05 Design](./05-design-tab.md), [06 Plan](./06-plan-tab.md), [08 Build](./08-build-tab.md).

The React app shell: project picker/creation, the three-tab navigation, shared server-state
and API client, and the cross-tab plumbing (e.g. "open this task in Design / Build").

## Stack & structure
- React + TypeScript + Vite.
- **Styling:** Tailwind CSS, plus a few headless primitives (e.g. Radix) for the custom
  graph/board/diff UIs.
- **Server state:** React Query (caching, invalidation, SSE-driven refetch). Avoids
  hand-rolled loading/stale logic for the many CRUD calls.
- **UI/global state:** Zustand for small cross-cutting state (active project, active tab,
  selected task id used across tabs).
- **Routing:** React Router. Routes double as the tab model and make deep links work:
  `/p/:project/design`, `/p/:project/plan`, `/p/:project/build/:taskId?`.

```
web/src/
├─ main.tsx, App.tsx              # router + providers (QueryClient, theme)
├─ lib/
│  ├─ api.ts                      # typed fetch client (attaches ?project=)
│  ├─ sse.ts                      # EventSource helper for execution streams
│  └─ types.ts                    # shared types mirroring API/01 schemas
├─ store/                         # zustand slices (project, ui, selection)
├─ components/                    # shared UI (Modal, PromptDialog, StatusBadge, ...)
├─ features/
│  ├─ projects/                   # picker + create flow
│  ├─ design/                     # tab 05
│  ├─ plan/                       # tab 06
│  └─ build/                      # tab 08
```

## API client (`lib/api.ts`)
- Thin typed wrappers per endpoint group (projects, docs, tasks, executions).
- Auto-attaches the active `project` param from the store.
- Centralized error shape handling (matches 02's `{ error: { code, message } }`).
- React Query hooks layered on top: `useDocs()`, `useTask(id)`, `useTaskGraph()`,
  `useExecution(id)`, with mutation hooks that invalidate the right query keys.

## Project picker & creation
First screen if no active project (and reachable from a menu).
- **Picker:** lists `GET /projects` (registry) with last-opened; selecting one sets active
  project and routes to `/p/:project/design`.
- **Create:** modal asking **name** + **root dir**. Root dir input: since browsers can't
  pick server-side paths, accept a typed absolute path (validated by `POST /projects`,
  which checks it exists and is a git repo). Show the resulting project path preview
  (`<root>/projects/<name>/`). On success, route into Design where the user is prompted to
  write the project spec (see 05's empty state).

## Tab navigation (app shell)
- Persistent top bar: project name + tab switcher (Design / Plan / Build).
- The shell is one layout; each tab is a routed feature module.
- **Cross-tab actions** (the glue these tabs need):
  - Plan side panel → "Open in Design" → route to Design with the task's doc open.
  - Plan side panel → "Execute" → route to Build for that task.
  - Build sidebar selection and Plan selection share `selectedTaskId` in the ui store so the
    same task stays in focus when switching tabs.

## Shared UI primitives (build once, reuse everywhere)
- `PromptDialog` — the "tell AI what you want" modal used by Design (new doc) and Plan
  (new task); supports an optional dependency picker (for tasks).
- `StatusBadge` / status color map — single source of truth for the status enum colors,
  reused by Plan graph, Plan board, and Build sidebar.
- `MetadataPanel` — renders/edits a metadata entry incl. the `custom` kv map; reused by
  Design's metadata section and Plan's task side panel.
- `Modal`, `Toast`, `ConfirmDialog`, `Spinner`.

## SSE helper (`lib/sse.ts`)
Wraps `EventSource` for `GET /executions/{id}/stream`; exposes a hook
`useExecutionStream(id)` that updates the React Query cache for that execution as `step`,
`question`, and `status` events arrive. Used by Build (08).

## Implementation steps
1. Vite + TS + providers; status color map + `StatusBadge`.
2. API client + React Query hooks for projects/docs/tasks.
3. Project picker + create flow against `POST /projects`.
4. App shell, routing, tab switcher, selection store.
5. Shared primitives: `PromptDialog`, `MetadataPanel`, `Modal`/`Toast`.
6. SSE helper (can stub until 08).

## Open questions
- Root-dir picking UX given browser limits — typed path for v1; a small local "browse"
  helper endpoint could come later.
