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

Clones are **fresh per execution** for now (a per-project mirror cache is a later optimization).

## Cross-repo dependencies (phase 3)
We already track each execution's branch (`ProgressState.branch`, reachable via
`task.executionId`). So when a task depends on an in-review+pushed task in **another** repo, that
repo's *context* clone is checked out at the **dependency's branch** (it's on the remote once
pushed). Same-repo dependencies keep today's branch-merge behavior.

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
