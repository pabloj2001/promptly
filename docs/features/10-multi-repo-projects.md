# 10 — Multi-repo projects (execution-level target repos)

A project can reference **multiple git repos**, not just its `root`. Each **task targets exactly
one repo** (its *execution target*); that repo is the only one written to and the one a PR is
opened against. Every other registered repo is cloned **read-only** into the execution workspace
so Claude has full cross-repo context. Work that spans repos is split into one task per repo,
chained with dependencies.

## Concepts & terminology
- **Project-primary repo** — the existing `root` git repo. Holds Promptly metadata/docs
  (`projects/<slug>/…`). Always present in a workspace. Registry id `"primary"`, no clone URL
  (it's local).
- **Additional repos** — referenced by clone URL in the project's **repo registry**.
- **Execution target repo** — the repo a task targets (`task.repo`, default = primary). Writable;
  branch + commit + push + PR happen here.
- **Context repos** — every other registered repo, cloned read-only into the workspace.

## Storage
- `projects/<slug>/repos.json` → `ProjectRepos { repos: [ProjectRepo] }`,
  `ProjectRepo { id, name, url, defaultBranch, primary }`. A `primary` entry (id `"primary"`,
  from `root`) is always present (seeded on read, re-injected on write); additional repos need a
  `url`.
- `MetadataEntry.repo: str | None` — the task's target repo id (None ⇒ primary).

## API
- `GET/PUT /repos` (project-scoped) — read/replace the registry (primary is preserved).
- `task.repo` is settable at create (`CreateTaskRequest.repo`) and via `PUT /metadata`.

## Execution workspace (phase 2)
`executions/<id>/workspace/<repo-name>/` per repo — **uniform** for every project (single-repo
projects included). `cwd` = `workspace/`. Setup:
1. Resolve the task's target repo.
2. Check out the target: primary → `git worktree add` from `root`; additional → clone the URL,
   create a `promptly/<task>-<id>` branch.
3. Clone every other registered repo read-only for context.
4. `base_sha` = target repo's base. Persist target repo id + path on the execution.

Writes are scoped to `workspace/<target>/` by the PreToolUse hook; `--add-dir` covers the whole
workspace (reads). Commit/push/diff/PR all operate on the target repo; **the PR is opened against
the execution's target repo** (its remote + default branch).

**Mirror cache.** Additional repos are checked out via a per-project bare mirror at
`executions/.cache/<repo-id>.git` (gitignored): `ensure_mirror` clones `--mirror` once then
`remote update`s it; each workspace checkout is `git clone --shared` from the mirror (objects
borrowed, so clones are tiny) with `origin` retargeted to the real URL for push/PR.

**Workspace pruning.** When a task is marked **done**, its execution workspaces are removed
(`prune_task_workspaces` → `worktree.remove_workspace`: drop linked worktrees, delete clones).
Pruning only happens once the task's **PR is merged** (checked via `gh`, `GET /tasks/{id}/pr-status`);
marking done with an unmerged/absent PR returns `409 pr_not_merged` so the UI can warn and retry
with `force` (which marks done but keeps the workspace, avoiding loss of unpushed work). The diff
endpoint returns an empty diff once a workspace is pruned.

## Cross-repo dependencies (implemented)
We track each execution's branch (`ProgressState.branch`, reachable via `task.executionId`). When a
task depends on an in-review+pushed task in **another** repo, that repo's *context* clone is checked
out at the **dependency's branch** (`_dep_branch_for_repo` → `clone_repo(base_branch=dep_branch)`
for additional repos, `add_worktree_detached(root, dep_branch)` for the primary; it's on the remote
once pushed), and the build prompt notes which context repos are pinned to a dependency. Same-repo
dependencies (targeting the *same* repo as the task) keep the branch-merge behavior
(`_merge_dependency_branches`).

## Out of scope / deferred
- No Plan-graph UI changes (repo selection lives in task create/edit + a project "Repos" settings
  panel only).
- Per-project clone/mirror caching (perf).
- Multi-repo *writes* in a single task (always one target; split cross-repo work into tasks).

## Complications & edge cases
- Auth for private additional repos (git credential helper / `gh`); clone failures surface as
  execution errors.
- Disk usage (N repos × M executions) — cleanup removes the whole `workspace/`.
- Each target repo needs its own remote + `gh` access for PRs.
- Accidental writes to context repos are denied by the hook.
