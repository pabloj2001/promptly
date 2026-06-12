"""Promptly execution MCP server (07).

Claude launches this as a private stdio child process (via ``--mcp-config``) for a
single execution. It exposes the *progress* tools the build session uses to report
what it's doing. The tools are deliberately **thin**: each one calls back into
Promptly's own localhost HTTP API (token-guarded), so uvicorn stays the single
writer of ``progress.json`` and owns SSE fan-out + the kill/resume control flow.

Bound to one execution via env (set in the mcp-config we pass per run):
  PROMPTLY_API_URL       e.g. http://127.0.0.1:8000
  PROMPTLY_PROJECT       active project name
  PROMPTLY_EXECUTION_ID  this execution's id
  PROMPTLY_TOKEN         shared secret for the internal endpoints

Run as: ``python -m api.mcp_server``
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("PROMPTLY_API_URL", "http://127.0.0.1:8000")
PROJECT = os.environ.get("PROMPTLY_PROJECT", "")
EXECUTION_ID = os.environ.get("PROMPTLY_EXECUTION_ID", "")
TOKEN = os.environ.get("PROMPTLY_TOKEN", "")

mcp = FastMCP("promptly")


async def _call(path: str, payload: dict) -> dict:
    url = f"{API_URL}/internal/executions/{EXECUTION_ID}/{path}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            params={"project": PROJECT},
            headers={"X-Promptly-Token": TOKEN},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}


@mcp.tool()
async def complete_step(title: str) -> str:
    """Mark the step with this exact `title` as done. Call it the moment you finish a
    step. The next step is automatically set to in-progress for you — you do not need
    to start it manually. Work through the plan one step at a time, in order."""
    await _call("steps/complete", {"title": title})
    return f"Marked '{title}' done; the next step is now in progress."


@mcp.tool()
async def revise_steps(steps: list[dict]) -> str:
    """Revise the plan when steps need to be added, removed, reordered, or reworded.
    Provide the ENTIRE updated list of steps (not just the changes), each as
    `{"title": "...", "detail": "<optional>", "done": true|false}` — set `done` to true
    for steps you've already completed so their state is preserved. The first not-done
    step automatically becomes in-progress."""
    await _call("steps/revise", {"steps": steps})
    return f"Plan revised to {len(steps)} steps."


@mcp.tool()
async def ask_question(question: str) -> str:
    """Ask the user a question when you are blocked and cannot proceed without their
    input. The build pauses; you will be resumed with their answer. Use sparingly —
    only when a decision genuinely requires the user."""
    await _call("ask", {"question": question})
    return "Question sent to the user; the session will pause until they answer."


@mcp.tool()
async def report_done(summary: str) -> str:
    """Call this when the task is fully implemented AND every step is marked done.
    Provide a short summary of what you changed. If any steps are still incomplete this
    call is rejected and tells you which remain — finish or revise them first. On
    success Promptly commits your work and moves the task to review."""
    result = await _call("report-done", {"summary": summary})
    if not result.get("complete", True):
        return result.get(
            "message",
            "Cannot finish: some steps are still incomplete. Complete or revise them, "
            "then call report_done again.",
        )
    return "Reported done. Promptly will commit and move the task to review."


if __name__ == "__main__":
    mcp.run()
