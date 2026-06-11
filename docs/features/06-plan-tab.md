# 06 — Plan Tab

**Depends on:** [02 API](./02-python-api-server.md) (`/tasks/graph`, status/metadata routes),
[04 Frontend Foundation](./04-frontend-foundation.md). Pairs with [05](./05-design-tab.md)
(open-in-Design) and [08](./08-build-tab.md) (execute).

Two views over the same task set: a **dependency graph** (default) and a **Kanban board**,
toggled at center-bottom. A shared **task side panel** (right) handles inspection/editing in
both views.

## Data
Source: `GET /tasks/graph?project=` → `{ nodes, edges }` (excludes `removed` unless
`includeRemoved`). Nodes carry full metadata; edges are `dependsOn` relations
(`from = dependent`, `to = dependency`). Status mutations go through
`PUT /tasks/{id}/status`; metadata edits via `PUT /tasks/{id}/metadata`.

## Graph view (default)
- **Canvas:** zoom (wheel) + pan (drag background). Strongly recommend **React Flow** — it
  gives pan/zoom, nodes, edges, and handles out of the box; a hand-rolled `<canvas>` would
  re-implement all of it. Use a custom node component for status coloring and a custom group
  node for task-group containers.
- **Nodes:** one per task, colored by status (shared status color map from 04). Show name +
  small status badge. `removed` hidden by default.
- **Edges:** drawn for each dependency. Direction conveys ordering (dependency → dependent).
- **Group containers:** tasks are enclosed in a labeled container per `taskGroup` (React
  Flow parent/group nodes or a background region). All tasks of a group cluster together;
  **dependency edges may cross group boundaries** and must still render correctly.
- **Layout:** auto-layout with a DAG layout engine (e.g. `dagre`/`elkjs`) grouped by
  `taskGroup`, computed client-side from the graph payload. Persist manual position nudges?
  v1: recompute layout each load (positions not persisted) — revisit if users want pinning.
- **Hover highlighting:** hovering a task highlights it plus its **entire dependency tree**
  (transitive ancestors *and* descendants). Distinguish direction by edge color:
  - edges toward tasks it **depends on** (ancestors) → **darker** highlight.
  - edges toward tasks that **depend on it** (descendants) → lighter highlight.
  Compute both closures client-side via BFS over the edge set; dim everything else.

## Board view (Kanban)
- Columns for each active status: **pending, in_progress, blocked, in_review, done**
  (`removed` excluded). Cards = tasks, grouped/labeled by `taskGroup` within columns
  (or a group filter), colored consistently with the graph.
- **Drag a card to another column** → optimistic move → `PUT /tasks/{id}/status`; revert on
  error. Respect illegal transitions surfaced by the API (e.g. can't manually set `done`
  while an execution runs).
- Clicking a card opens the same side panel.

## View toggle
Center-bottom control switches Graph ⇄ Board. Persist the choice per project in the ui
store. Both views read the same `useTaskGraph()` data.

## Task side panel (right) — shared by both views
Opens on node/card click. Shows full metadata, editable (reuses `MetadataPanel`, 04):
name, description, status, task group, related PRs, `dependsOn`, custom fields, executionId.
Plus:
- **Comes before / comes after:** two lists — direct dependencies (before) and direct
  dependents (after) — derived from edges; click to navigate to that task.
- **Open in Design** → routes to Design with this task's doc open (04 cross-tab action).
- **Execute** → routes to Build for this task (starts/opens its execution; see 08).

## Add a task (both views)
A hover/floating **+** button opens `PromptDialog` (04): prompt for what the task should be
+ optional dependency picker (preselect a task if one is selected). Submit → `POST /tasks`
→ AI generates the task spec + metadata → node/card appears. New task defaults to `pending`.

## Implementation steps
1. `useTaskGraph()` + status color map; React Flow canvas with custom status nodes.
2. Group containers per `taskGroup`; DAG auto-layout (dagre/elk), cross-group edges.
3. Hover dependency-tree highlighting (ancestor/descendant BFS, two-tone edges).
4. Shared task side panel (metadata edit + before/after lists + Open-in-Design + Execute).
5. Board view with drag-to-change-status (optimistic + transition validation).
6. View toggle + persistence; floating "add task" via `PromptDialog`.

## Open questions
- Persist manual node positions? Default no (auto-layout each load); add later if requested.
- Group containers + a clean DAG layout can fight each other — may need per-group sub-layout
  then arrange groups. Prototype layout early; it's the riskiest part of this tab.
- Cross-group edges should remain readable (consider routing/curved edges over containers).
