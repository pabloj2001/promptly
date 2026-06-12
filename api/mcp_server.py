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
async def plan_steps(steps: list[str]) -> str:
    """Record your plan as an ordered list of step titles. Call this once after you
    have read the task spec and understood the work, before you start coding."""
    await _call("steps/plan", {"titles": steps})
    return f"Recorded {len(steps)} steps."


@mcp.tool()
async def add_step(title: str, detail: str = "") -> str:
    """Append a step you discovered mid-build that wasn't in your original plan."""
    await _call("steps/add", {"title": title, "detail": detail})
    return "Step added."


@mcp.tool()
async def update_step(
    title: str = "", step_id: str = "", status: str = "", detail: str = ""
) -> str:
    """Update a step's status as you work. Identify it by `title` (or `step_id`).
    `status` is one of: pending, in_progress, done, skipped. Mark a step
    in_progress when you start it and done when you finish."""
    await _call(
        "steps/update",
        {"title": title or None, "stepId": step_id or None,
         "status": status or None, "detail": detail or None},
    )
    return "Step updated."


@mcp.tool()
async def ask_question(question: str) -> str:
    """Ask the user a question when you are blocked and cannot proceed without their
    input. The build pauses; you will be resumed with their answer. Use sparingly —
    only when a decision genuinely requires the user."""
    await _call("ask", {"question": question})
    return "Question sent to the user; the session will pause until they answer."


@mcp.tool()
async def report_done(summary: str) -> str:
    """Call this when the task is fully implemented. Provide a short summary of what
    you changed. Promptly will commit your work and move the task to review."""
    await _call("report-done", {"summary": summary})
    return "Reported done. Promptly will commit and move the task to review."


if __name__ == "__main__":
    mcp.run()
