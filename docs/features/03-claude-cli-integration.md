# 03 — Claude CLI Integration

**Depends on:** [01](./01-data-model-and-storage.md), [02](./02-python-api-server.md),
[09 Prompts & Permissions](./09-prompts-and-permissions.md).
**Blocks:** prompt-driven doc/task creation, comment addressing, doc chat, [07 Execution Engine](./07-execution-engine.md).

All AI work goes through the **Claude CLI in headless mode**, spawned as a subprocess by
the backend. This doc covers the two usage modes — **generation** (authoring/editing docs &
tasks, doc chat, addressing comments) and **stateful sessions** (task execution, a turn-based
loop where Claude reports progress via a **`--json-schema` structured-output command** each
turn — no MCP).

> Flags below are **verified against CLI v2.1.173**. Notably: there is **no
> `--permission-prompt-tool`** and **no `--max-turns`** in this version — earlier drafts
> assumed both. We use a `PreToolUse` hook for approvals (09/07) and a subprocess timeout
> instead of a turn ceiling. Re-verify with `claude --help` on upgrades.

> **Context model (changed per user feedback):** generation no longer inlines a curated
> context blob. Instead Claude is given **read access to the whole repo** (via the per-project
> permissions config, [09](./09-prompts-and-permissions.md)) and is *instructed to read*
> `CLAUDE.md`, the project spec, related tasks/docs, and source before writing. Prompts are
> **Jinja2 templates** in the top-level `prompts/` dir, not inline strings (09).

## The Claude CLI headless surface (what we use)
- `claude -p "<prompt>"` — non-interactive ("print") mode: run once, emit result, exit.
- `--output-format stream-json` — newline-delimited JSON events (assistant messages, tool
  calls, and a final `result` event carrying `session_id`, cost, etc.). Parse this rather
  than plain text so we can capture the session id and tool activity.
- `--input-format stream-json` — lets us feed structured turns (used to answer questions
  mid-session without losing context).
- `--resume <session-id>` — continue a prior session (key for execution + Q&A + feedback).
- `--model <id>` — pin the model (default to the latest capable model, e.g. `claude-opus-4-8`).
- `--json-schema <schema>` — constrain a `-p` turn so its result carries a schema-valid
  `structured_output` object. This is how the execution loop gets a reliable progress command
  per turn (below) — replaces the old MCP progress server.
- `--allowedTools` / `--disallowedTools` — gate tools; e.g. allow file/edit tools and
  file/edit tools during execution. (Most permission control comes from `--settings`, below.)
- `--settings <json|file>` — supply a Claude `settings.json` with `permissions:{allow,deny,
  ask}`, `additionalDirectories`, `defaultMode`, and a `PreToolUse` hook. **This is how we
  grant whole-repo reads while constraining writes** — Promptly compiles the per-project
  `permissions.json` profile (09) into this object per call. Reads need no approval; in
  headless `-p` an un-approved write/exec auto-denies unless allowed.
- `--permission-mode <mode>` — `default | acceptEdits | plan | dontAsk | bypassPermissions`.
  Generation uses `default` (reads free, writes denied); execution uses `acceptEdits` so
  edits inside the worktree apply unattended (09/07).
- `--add-dir <dir>` — grant file access to a directory beyond `cwd`. We add the **repo root**
  so Claude can read any file for context, plus any `additionalReadDirs` from the project's
  `permissions.json` (09).
- `--append-system-prompt` — inject the rendered Promptly system prompt (output contract, the
  "read the repo first" instruction, and for execution how to return the progress commands).
- Working directory = the subprocess `cwd`: the **repo root** for generation (so reads span
  the repo), the **worktree** for execution.

## ClaudeService (the wrapper)
A module that owns subprocess lifecycle and stream parsing. Keep it transport-only; callers
(routers, ExecutionManager) decide prompts and what to persist.

```python
class ClaudeService:
    async def generate(self, *, prompt, system=None, cwd, settings=None,
                       add_dirs=None, permission_mode=None, model=None,
                       session_id=None) -> GenResult:
        """One-shot / single conversational turn. Spawns `claude -p ...
        --output-format json`, returns {text, session_id, cost}. Pass
        session_id to continue a doc-chat conversation (--resume)."""

    def build_run_command(self, root, project, *, execution_id, worktree,
                          prompt, session_id=None, granted=None) -> RunSpec:
        """Compile one build-session turn: `claude -p --json-schema <command schema>
        --output-format stream-json` + settings/permission-mode/PreToolUse hook.
        ExecutionManager spawns it, streams events (live activity), and reads the
        turn's structured_output command (see api/services/exec_protocol.py)."""
```
Implementation notes:
- Spawn with `asyncio.create_subprocess_exec`. Generation uses `--output-format json` (one
  `result` object — cleaner for single turns); execution uses `stream-json` so we see tool
  activity live. Capture stderr for error reporting.
- Always extract and persist `session_id` (from the `result` event / final result) — it's
  how we resume for doc chat, execution answers, feedback, and PR-comment review.
- No `--max-turns` in this CLI version: bound generation with a **subprocess timeout**;
  execution runs long (no hard timeout, but support cancellation by killing the process tree).
- Compile permission settings from the project's `permissions.json` profile (09) into the
  `--settings` payload + `--permission-mode` + `--add-dir` for every call.

## Mode A — generation (authoring & editing)
Used by `POST /docs`, `POST /tasks`, `POST /docs|tasks/{id}/address`, and the doc **chat**
(`POST /docs|tasks/{id}/chat`).

**Repo-read context (not inline).** Generation runs with `cwd = repo root` and the
**generation** permissions profile (09): reads allowed across the whole repo, all writes
denied. The system prompt (a Jinja2 template, 09) instructs Claude to **read first** —
`CLAUDE.md` files, the project spec, related task specs and docs, and the relevant source —
then produce the document. Claude returns text; *we* write the files (it cannot write).

**Runs as a background operation.** Authoring is slow, so these calls don't block the HTTP
request. The API creates/marks the target with an `operation` (01) and returns immediately;
ClaudeService runs in a background task; on completion we write the result, clear the
operation, and publish an event over the operations SSE stream (02). The Design tab shows a
loading state meanwhile (05).

- **Create a doc/task from a prompt** (`generate_doc`/`generate_task` templates). For a brand-
  new item the API first creates a placeholder metadata entry with `operation.status=running`
  and an empty body (so it appears in the sidebar with a spinner), then fills body + metadata
  (`name`, `description`) when generation finishes. Metadata comes back as a JSON object we
  parse leniently (one retry), or via a cheap follow-up extraction if needed (09 open Q).
  - **First doc special case** (`generate_project_spec` template): if no `project_spec`
    exists the framing is different — read `CLAUDE.md`/skim the codebase, draft the spec from
    the user's description, save as `project.md`.
- **Chat — conversational edits/questions** (`chat_edit` template). A per-doc chat where the
  user sends one message and gets one response (not a batch). Backed by a resumable Claude
  **session** (`session_id` persisted with the chat, 01) so the conversation has memory and
  full repo read access. A turn may **revise the doc body** (the AI is its author); the
  updated body is written and the doc shows the in-progress state while the turn runs.
  Highlight → "Ask AI" feeds the quoted span into this chat (05).
- **Address comments** (`address_comments` template). Batch-revise the doc to address its
  unresolved highlight comments; input = current body + unresolved comments (with quoted
  anchors). Returns a proposed revision for preview; on accept the body is replaced and
  addressed comments marked `resolved` (05).
- **Plan tasks from the spec** (`plan_tasks` template). Reads the project spec + repo and
  returns a **task breakdown** as a JSON list of stubs `{name, description, taskGroup,
  dependsOn:[names]}`. The API creates a placeholder per stub (resolving `dependsOn` names →
  ids) and then runs each task's body generation through the normal `generate_task` flow, so
  the tasks appear immediately and fill in asynchronously (02/05/06).

> **Import writes the body verbatim, then fills metadata with AI.** Importing a doc or task
> (paste/upload one or more files, 05) writes each provided body **verbatim** (no AI touches the
> body), routing by the chosen type (doc vs. task). It then kicks off a **background
> metadata-only generation op** (`import_metadata` template → `ClaudeService.
> derive_import_metadata`) that reads the body + repo and patches `description` (and, for tasks,
> `taskGroup`); the body is never modified. Reuses the operations SSE + `operation` running flag
> like normal generation.

## Mode B — stateful execution session (turn-based, structured-output protocol)
Used by the Execution Engine ([07](./07-execution-engine.md)). The build session is **not** a
single long run and uses **no MCP server**. It's a backend-driven loop of `claude -p` **turns**,
each constrained with **`--json-schema`** so its result carries one schema-validated
**`structured_output`** command. Each turn runs in the execution's `worktree/`, does real work
with the normal tools, and returns one command; the engine dispatches it and `--resume`s for the
next turn. `session_id` is persisted to `progress.json` for resumes (answer / feedback / Try
again / review PR comments).

### The command protocol (Claude → Promptly)
Instead of MCP tools, Claude reports progress by returning ONE command per turn. The step list
is still **pre-planned** in a separate call before the loop starts (07). Commands (`type`
required):
| Command | Effect |
|---------|--------|
| `step_complete{title}` | Mark the named step `done`; next pending step auto-advances. |
| `revise_steps{steps:[{title,detail?,done}]}` | Replace the **entire** plan; re-derive the active step. |
| `question{question}` | Clarifying question → `awaiting_input` (loop pauses). |
| `issue{issue,detail?}` | Blocker/error → `awaiting_input`, surfaced as a red blocker. |
| `done{summary}` | Task complete → `in_review`. If any step is incomplete, the loop resumes with a correction instead. |
| `thinking{text}` | Optional surfaced progress note; the loop continues. |

We read the command from the live `stream-json` `result` event's `structured_output` (the same
stream surfaces the live line-of-thinking as a compact `activity`). **Fallback:** if a turn's
process is lost (e.g. server restart), the command is recovered from the session transcript
(`~/.claude/projects/*/<session_id>.jsonl`, recorded as a `tool_use` named `StructuredOutput`).
See `api/services/exec_protocol.py`.

> **Permission approvals** stay a **`PreToolUse` hook** (09) — the one remaining internal
> callback — which records a pending permission request, emits the SSE `permission` event, and
> pauses the loop until the user answers (see [07](./07-execution-engine.md)).

> **Errors never auto-resume.** A turn that returns no valid command (Anthropic down,
> connectivity, CLI crash) or a server restart marks the execution `failed` (keeping the
> session), flags the task red, and the user resumes via **Try again** (`POST
> /executions/{id}/resume`) — see [07](./07-execution-engine.md).

## Prompt assets
Prompts are **Jinja2 templates in the top-level `prompts/` dir** (not `api/prompts/`, not
inline strings) so they're easy to edit without touching code — see
[09](./09-prompts-and-permissions.md) for the list, variables, and the `PromptLibrary`
loader. ClaudeService renders a template and passes the result via `--append-system-prompt`.

## Implementation steps
1. `PromptLibrary` (Jinja2) + port prompts to `prompts/*.md.j2` (09).
2. Permissions compiler: `permissions.json` profile → `--settings`/`--permission-mode`/
   `--add-dir` (09).
3. ClaudeService `generate()` (json output, session resume for chat) + lenient structured
   parse + timeout.
4. Wire async `POST /docs`, `POST /tasks`, `/address`, `/chat` as background operations (02)
   that publish to the operations SSE stream.
5. `build_run_command()` (stream-json + `--json-schema`) + the ExecutionManager turn loop with
   event callback + cancellation (07).
6. `exec_protocol.py`: command schema + parse the turn's `structured_output` / transcript
   fallback; the `PreToolUse` approval hook (07/09) is the only remaining internal callback.
7. Tests: command parse + transcript fallback fixtures; `_handle_command` dispatch mutates the
   right file + publishes events; generation produces valid metadata; chat resume continuity.

## Open questions
- Structured metadata extraction with repo-reading enabled (multi-turn): instruct "read
  first, then output ONLY the JSON," parse leniently with one retry; fall back to a cheap
  second extraction pass if reliability is poor (09).
- Chat turns that revise the body: return the whole revised body each turn, or a diff/patch
  we apply? Start with whole-body for simplicity; revisit if large docs make that costly.
