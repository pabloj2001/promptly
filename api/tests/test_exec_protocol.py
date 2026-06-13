"""Tests for the JSON structured-output protocol (07) and its dispatch."""

from __future__ import annotations

import json

from api.models import ProgressStatus
from api.services import exec_protocol
from api.services.execution import ExecutionManager, SSEBus


def test_command_from_result_event():
    ev = {"type": "result", "structured_output": {"type": "done", "summary": "ok"}}
    assert exec_protocol.command_from_result_event(ev) == {"type": "done", "summary": "ok"}
    assert exec_protocol.command_from_result_event({"type": "result"}) is None
    # not a known command type
    assert exec_protocol.command_from_result_event(
        {"type": "result", "structured_output": {"type": "nope"}}) is None


def test_activity_summary_tool_and_text():
    tool_ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "a/b.py"}}]}}
    assert exec_protocol.activity_summary(tool_ev) == "Edit: a/b.py"
    text_ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Reading the spec\nmore"}]}}
    assert exec_protocol.activity_summary(text_ev) == "Reading the spec"
    # StructuredOutput tool_use is ignored as activity (it's the command, not work)
    so_ev = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "StructuredOutput", "input": {"type": "done"}}]}}
    assert exec_protocol.activity_summary(so_ev) is None


def test_read_transcript_command(tmp_path, monkeypatch):
    sid = "abc-123"
    proj_dir = tmp_path / "projects" / "-some-cwd"
    proj_dir.mkdir(parents=True)
    lines = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "StructuredOutput",
             "input": {"type": "step_complete", "title": "one"}}]}},
        {"type": "user", "message": {"content": "ok"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "StructuredOutput",
             "input": {"type": "question", "question": "Which DB?"}}]}},
    ]
    (proj_dir / f"{sid}.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    cmd = exec_protocol.read_transcript_command(sid)
    assert cmd == {"type": "question", "question": "Which DB?"}  # the LAST command
    assert exec_protocol.read_transcript_command("missing") is None


# ── _handle_command dispatch ──────────────────────────────────────────────────────


def _em_with_exec(storage, root, eid="x1", steps=None):
    storage.create_project("Demo", root)
    task = storage.create_entry(root, "Demo", type="task", display_name="T")
    storage.create_execution(root, "Demo", eid, task.id)
    if steps:
        storage.seed_steps(root, "Demo", eid, steps)
    return ExecutionManager(storage, SSEBus(), claude=None), task.id


def test_handle_step_complete_continues(storage, root):
    em, tid = _em_with_exec(storage, root, steps=[{"title": "a"}, {"title": "b"}])
    out = em._handle_command(root, "Demo", "x1", tid,
                             {"type": "step_complete", "title": "a"})
    assert out is not None  # continue prompt
    prog = storage.read_progress(root, "Demo", "x1")
    assert prog.steps[0].status == "done" and prog.steps[1].status == "in_progress"


def test_handle_question_pauses(storage, root):
    em, tid = _em_with_exec(storage, root)
    out = em._handle_command(root, "Demo", "x1", tid,
                             {"type": "question", "question": "Which DB?"})
    assert out is None  # pause
    prog = storage.read_progress(root, "Demo", "x1")
    assert prog.status == ProgressStatus.awaiting_input.value
    assert prog.pending_questions[-1].kind == "question"


def test_handle_issue_pauses_as_issue(storage, root):
    em, tid = _em_with_exec(storage, root)
    out = em._handle_command(root, "Demo", "x1", tid,
                             {"type": "issue", "issue": "npm down", "detail": "ETIMEDOUT"})
    assert out is None
    prog = storage.read_progress(root, "Demo", "x1")
    assert prog.status == ProgressStatus.awaiting_input.value
    q = prog.pending_questions[-1]
    assert q.kind == "issue" and "ETIMEDOUT" in q.question


def test_handle_done_incomplete_returns_correction(storage, root):
    em, tid = _em_with_exec(storage, root, steps=[{"title": "a"}, {"title": "b"}])
    out = em._handle_command(root, "Demo", "x1", tid,
                             {"type": "done", "summary": "x"})
    assert out is not None and "incomplete" in out.lower()
    # not finalized
    assert storage.read_progress(root, "Demo", "x1").status != ProgressStatus.completed.value


def test_set_error_flags_task(storage, root):
    em, tid = _em_with_exec(storage, root)
    em._set_error(root, "Demo", "x1", tid, "anthropic down")
    prog = storage.read_progress(root, "Demo", "x1")
    assert prog.status == ProgressStatus.failed.value and "anthropic" in (prog.error or "")
    assert storage.get_entry(root, "Demo", "tasks", tid).execution_error is True
