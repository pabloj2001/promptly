# 09 — Prompts & Permissions (cross-cutting)

**Used by:** [03 Claude CLI](./03-claude-cli-integration.md), [07 Execution Engine](./07-execution-engine.md).
**Depends on:** [01 Data Model](./01-data-model-and-storage.md), [02 API](./02-python-api-server.md).

Two cross-cutting concerns that several features share: where prompt text lives (and
how it's templated) and how we grant Claude file access safely (per-project, user-editable
permissions). Both are driven by user feedback:

> - "I want the prompts stored separate from the code so they're easy to modify" (with light
>   templating).
> - "AI operations need context on the entire repo — allow reading any file in the repo
>   instead of providing inline context. Have a per-project permissions config under the
>   project folder the user can edit to allow more."
> - "Tell the AI to read `CLAUDE.md` files, the project spec, tasks, etc. before writing docs;
>   the first-time project-spec prompt should be slightly different."

## Part A — Prompts as editable templates

### Where prompts live
All prompt text lives in a top-level **`prompts/`** directory at the repo root — deliberately
**outside the application code** so it's easy to find and edit without touching Python:

```
prompts/
├─ generate_doc.md.j2
├─ generate_task.md.j2
├─ generate_project_spec.md.j2     # first-time spec — different framing
├─ plan_tasks.md.j2                # break the project spec into a task list
├─ chat_edit.md.j2                 # conversational doc change requests
├─ address_comments.md.j2          # batch-address highlight comments
└─ execute_task.md.j2              # execution session system prompt (07)
```

### Templating
Use **Jinja2** (small, ubiquitous, no custom engine to maintain). Templates are `*.md.j2`
and rendered with a context dict. Keep logic in the template minimal (conditionals for the
first-time-spec case, loops over dependency names) — anything heavier belongs in Python.

A tiny `PromptLibrary` wrapper (in `api/services/prompts.py`) loads the directory once and
exposes `render(name, **vars) -> str`. ClaudeService calls it; it never inlines prompt
strings.

### Shared instruction: read the repo first
Every authoring prompt instructs Claude to **ground itself in the repo before writing**:

> Before writing, read the relevant context: any `CLAUDE.md` files in the repository, the
> project spec (`projects/<name>/project.md`), related task specs under
> `projects/<name>/tasks/`, supplemental docs under `projects/<name>/docs/`, and the actual
> source code the doc/task concerns. Use your file-reading tools — do not guess.

This replaces the previous "inline a curated context blob" approach: Claude now has
**read access to the whole repo** (Part B) and is told to use it. We may still pass small
pointers (the active project name/path, the target file), but not the full bodies.

- **First-time project spec** (`generate_project_spec.md.j2`): there is no `project.md` yet,
  so the framing is different — read `CLAUDE.md` and skim the codebase to understand what
  exists, then draft the spec from the user's description. No sibling docs/tasks to honor.

### Template variables (typical)
`project_name`, `project_path` (`<root>/projects/<name>/`), `repo_root`, `doc_type`,
`user_request`, `dependency_names` (for tasks), `is_first_spec` (bool), and for chat/address:
`conversation` / `comments`. Each template documents its own expected vars in a header
comment.

## Part B — Per-project permissions

### Goal
AI operations should be able to **read any file in the repo** for context, while writes stay
constrained (generation writes nothing; execution writes only inside its worktree). The set
of allowed paths/tools is a **per-project config the user can edit** to grant more.

We build on Claude Code's native permission system
(https://code.claude.com/docs/en/permissions) rather than inventing our own:
- **Reads require no approval**; Bash and edits do. In headless `-p` mode an un-approved
  prompt auto-denies. So "read the whole repo" = run with the repo root as a working/added
  directory and simply **don't deny reads**.
- Rules live in a `settings.json`-shaped object: `permissions: { allow, deny, ask }` with
  gitignore-style path rules (`Read(/src/**)`, `Edit(/projects/**)`, `Bash(git diff:*)`),
  plus `additionalDirectories` and `defaultMode`.
- We supply settings to each CLI call via **`--settings <json|file>`** and set
  **`--permission-mode`**; we add the repo root with **`--add-dir`** / `cwd`.

### The per-project config file
`<root>/projects/<name>/permissions.json` — Promptly-managed but **user-editable**. It
declares two **profiles** (Promptly compiles each into the flags/settings for a CLI call):

```jsonc
{
  "version": 1,
  // Extra directories outside the repo the user wants readable (default: none).
  "additionalReadDirs": [],
  "generation": {
    "permissionMode": "default",
    "allow": ["Read", "Grep", "Glob"],
    "deny": ["Edit", "Write", "Bash"]         // generation never modifies anything
  },
  "execution": {
    "permissionMode": "auto",                 // unattended (no prompts)
    "allow": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
    "deny": [],
    "askFallback": false                      // hard-deny out-of-scope writes
  }
}
```

- **generation** (Mode A, 03): `cwd = repo root`, reads allowed across the whole repo, all
  writes denied. Claude reads `CLAUDE.md`/spec/tasks/source, returns the document; *we* write
  the file.
- **execution** (Mode B, 07): `cwd = worktree`, runs **unattended in `auto` mode** (no prompts)
  but **explicitly scoped**: reads limited to the project's `docs/` + `tasks/` (`--add-dir`)
  plus the worktree; writes limited to the worktree by the PreToolUse hook (hard-denies edits
  outside it — verified honored under `auto`). Bash runs in the worktree. The worktree
  isolates changes until a PR. `askFallback: true` routes out-of-scope writes to the user
  instead of denying; `bypassPermissions` drops the hook for fully unscoped access. A future
  per-command **whitelist/blacklist** plugs into the hook + allow/deny rules.
- The user can edit this file to tighten or widen access (mode, `allow`/`deny`,
  `additionalReadDirs`). Promptly reads it per call; missing file → sensible defaults above.

### Approvals (replacing the non-existent `--permission-prompt-tool`)
The CLI version we target has **no `--permission-prompt-tool` flag**. The supported way to
route a permission decision back to us is a **`PreToolUse` hook**: a small script registered
in the settings we pass, which fires before a tool call and can allow / ask / deny it.

For execution (07), the hook recognizes out-of-scope actions (write/exec outside the
worktree, a Bash command not on the allowlist), POSTs a **pending permission request** to
Promptly's internal API (which records it in the execution's `progress.json`, emits the SSE
`permission` event, and **kills the subprocess**), and **denies** the call. It does **not**
block — the kill-and-resume model means the user's decision re-spawns the session with
`--resume` (granted tools added to `--allowedTools`). Reads and in-worktree edits pass
through without a prompt. Details live in [07](./07-execution-engine.md).

## Implementation steps
1. `prompts/` dir + Jinja2 + `PromptLibrary.render()`; port existing prompts to `*.md.j2`.
2. Add the "read the repo first" instruction to every authoring template; add the
   first-time-spec variant.
3. `permissions.json` schema + loader (defaults when absent) in StorageService (01).
4. A `build_cli_permissions(profile)` helper that compiles a profile into `--settings` JSON +
   `--permission-mode` + `--add-dir` for ClaudeService (03) and the execution run loop (07).
5. The execution `PreToolUse` hook script + its wiring into `progress.json`/SSE (07).

## Open questions
- Do we write a real `.claude/settings.json` into the repo, or pass settings only via
  `--settings` (ephemeral, nothing committed)? Lean **ephemeral `--settings`** so we don't
  litter the user's repo; `permissions.json` stays the single source the user edits.
- Structured generation vs. agentic reading: letting Claude read files makes generation
  multi-turn, which previously made structured `{name,description,body}` output less
  reliable. Mitigation: instruct "read first, then output ONLY the JSON object," parse
  leniently with one retry, and if needed split into a read/draft pass + a cheap
  metadata-extraction pass. Validate during implementation.
