# 03 — Claude CLI Integration

**Depends on:** [01](./01-data-model-and-storage.md), [02](./02-python-api-server.md).
**Blocks:** prompt-driven doc/task creation, comment addressing, [07 Execution Engine](./07-execution-engine.md).

All AI work goes through the **Claude CLI in headless mode**, spawned as a subprocess by
the backend. This doc covers the two usage modes — **one-shot generation** (docs/tasks,
addressing comments) and **stateful sessions** (task execution) — plus the **MCP tool
server** Claude calls back into to report progress.

> Verify the exact CLI flags against the installed version (`claude --help`) before relying
> on them; the headless surface is stable but flag names should be confirmed.

## The Claude CLI headless surface (what we use)
- `claude -p "<prompt>"` — non-interactive ("print") mode: run once, emit result, exit.
- `--output-format stream-json` — newline-delimited JSON events (assistant messages, tool
  calls, and a final `result` event carrying `session_id`, cost, etc.). Parse this rather
  than plain text so we can capture the session id and tool activity.
- `--input-format stream-json` — lets us feed structured turns (used to answer questions
  mid-session without losing context).
- `--resume <session-id>` — continue a prior session (key for execution + Q&A + feedback).
- `--model <id>` — pin the model (default to the latest capable model, e.g. `claude-opus-4-8`).
- `--mcp-config <json|file>` — register our MCP server (below).
- `--allowedTools` / `--disallowedTools` — gate tools; e.g. allow `mcp__promptly__*` and
  file/edit tools during execution; restrict to nothing destructive during doc generation.
- `--permission-mode` + `--permission-prompt-tool <mcp-tool>` — for execution we run
  **unattended but sandboxed to the worktree** (read/write/execute only there). Instead of
  auto-denying anything out of scope, the CLI routes the permission request to our
  permission-prompt MCP tool so the user can decide in the Build UI (see permissions model
  in [07](./07-execution-engine.md)).
- `--add-dir` — grant access to extra paths. In v1, execution always adds the **live
  project docs dir** (`<root>/projects/<name>/`) **read-only** so Claude can consult
  `project.md`, `docs/`, and `tasks/` while working; later it also carries user-registered
  read-only dirs (see permissions model in [07](./07-execution-engine.md)).
- `--append-system-prompt` — inject Promptly-specific instructions (output contract, how to
  call the MCP progress tools, where it is and isn't allowed to write).
- Working directory = the subprocess `cwd` (the project dir for generation; the worktree
  for execution). Use `--add-dir` if Claude needs read access to a sibling path.

## ClaudeService (the wrapper)
A module that owns subprocess lifecycle and stream parsing. Keep it transport-only; callers
(routers, ExecutionManager) decide prompts and what to persist.

```python
class ClaudeService:
    async def generate(self, *, prompt, system=None, cwd, allowed_tools=None,
                       model=None) -> GenResult:
        """One-shot. Spawns `claude -p ... --output-format stream-json`,
        accumulates the assistant text, returns {text, session_id, cost}."""

    async def run_session(self, *, prompt, cwd, session_id=None, resume=False,
                          mcp_config, allowed_tools, system=None,
                          on_event) -> SessionResult:
        """Stateful. Streams events to `on_event` callback (the ExecutionManager
        turns these into SSE + progress.json writes). Returns final session_id+status."""
```
Implementation notes:
- Spawn with `asyncio.create_subprocess_exec`; read stdout line-by-line; `json.loads` each
  line; dispatch by event type. Capture stderr for error reporting.
- Always extract and persist `session_id` from the final `result` event — it's how we
  resume for answers, feedback, and PR-comment review.
- Enforce a timeout / `--max-turns` ceiling for generation calls; execution calls run long
  (no hard timeout, but support cancellation by killing the process tree).

## Mode A — one-shot generation
Used by `POST /docs`, `POST /tasks`, and `POST /docs/{id}/address`.

**Read access to project docs.** Like execution, generation always grants Claude
**read-only** access to the live project docs (`<root>/projects/<name>/`: `project.md`,
`docs/`, `tasks/`) via `--add-dir` so a new/revised doc or task is consistent with the spec,
sibling docs, and other task specs. Generation still keeps **write/edit/file-creation tools
disabled** — Claude reads context and returns text; *we* write the files. (We may still pass
a short curated context inline, but Claude can read the full set itself.)

- **Create a doc/task from a prompt.** System prompt establishes: "You write a single
  markdown document. Do not create files. Output only the document body." We pass the user
  prompt plus project context (the project spec, names/descriptions of existing docs/tasks
  so the new one is consistent, and selected `dependsOn` for tasks). The returned text
  becomes the `.md` body; metadata (`name`, `description`) can be asked of Claude in a
  structured tail or inferred, then written to `docs.json`/`tasks.json`.
  - **First doc special case:** if no project_spec exists, the prompt is framed as
    "write the main project spec" and the result is saved as `project.md`.
- **Address comments.** System prompt: "Revise the document to address the inline comments;
  preserve unrelated content; output the full revised body." Input = current body +
  unresolved comments (with their quoted anchors). The result is returned for preview;
  on accept, body is replaced and addressed comments marked `resolved`.
- Generation runs with write/edit/file-creation tools disabled (Claude returns text; *we*
  write files) but with read-only access to the project docs (above) so it stays consistent.

## Mode B — stateful execution session
Used by the Execution Engine ([07](./07-execution-engine.md)). The session:
1. Starts in the execution's `worktree/` with the task spec + project context as the prompt.
2. Has the **MCP server** registered so Claude reports steps/questions via tools.
3. Persists its `session_id` into `progress.json` so later actions resume it:
   - **Answer a question:** resume the session, deliver the user's answer.
   - **Feedback (in_review → in_progress):** resume with the feedback text.
   - **Review PR comments:** resume with the PR review comments.

## The MCP tool server (Claude → Promptly callback)
So Claude updates execution state through **typed tools** instead of editing
`progress.json` directly (safer; can't corrupt the file or touch other tasks). Ship a small
**stdio MCP server** (Python, same package) registered via `--mcp-config`.

Tools exposed (namespace `promptly`):
| Tool | Purpose |
|------|---------|
| `plan_steps(steps: [{title, detail}])` | Claude declares its plan; replaces/sets `steps`. |
| `update_step(id, status, detail?)` | Mark a step in_progress/done/skipped. |
| `add_step(title, detail?)` | Append a step discovered mid-flight. |
| `ask_question(question) -> id` | Surface a clarifying question; execution enters `awaiting_input`. |
| `report_done(summary)` | Signal task complete → status `in_review`. |
| `request_permission(tool, request) -> decision` | The CLI's `--permission-prompt-tool` target: surfaces an out-of-scope action to the user (Allow/Deny) and returns their decision. Execution enters `awaiting_input` until answered. |

- The MCP server is bound to **one execution id** (passed via env/config when spawned) and
  calls back into StorageService/ExecutionManager to mutate *only* that execution's
  `progress.json`, then publishes the change to the SSE bus.
- Register with `--mcp-config '{"mcpServers":{"promptly":{...}}}'` and
  `--allowedTools mcp__promptly__*` (plus the edit/file tools the task needs).
- Fallback (discouraged): instruct Claude to edit `progress.json` directly. Documented only
  so reviewers know why MCP was chosen.

## Prompt assets
Keep prompt templates in `api/prompts/` (versioned files), not inline strings:
`generate_doc.md`, `generate_task.md`, `generate_project_spec.md`, `address_comments.md`,
`execute_task.md`. Each documents its expected inputs and output contract.

## Implementation steps
1. ClaudeService one-shot `generate()` + stream-json parser + session-id capture.
2. Wire `POST /docs`, `POST /tasks`, `POST /docs/{id}/address` to it; write prompt templates.
3. `run_session()` with event callback + cancellation.
4. MCP tool server (stdio) bound to an execution; the five tools above.
5. Tests: parser against recorded stream-json fixtures; MCP tools mutate the right file
   and publish events; generation produces valid metadata.

## Open questions
- Structured metadata extraction: ask Claude for a JSON tail vs. a second cheap call vs.
  infer name/description locally? Start with a JSON tail in a fenced block, parsed leniently.
- Confirm the installed CLI's exact flag for routing permission prompts to an MCP tool
  (`--permission-prompt-tool`) and the sandbox/scoping flags that confine writes to the
  worktree; the permissions model in [07](./07-execution-engine.md) assumes both exist.
