"""Execution engine tests (07).

Covers the deterministic pieces — worktree lifecycle (real git), the internal
MCP/hook callbacks, the run-loop finalize logic, the kill-and-resume control flow,
and the PreToolUse hook decisions — without spawning a real ``claude`` process
(ClaudeService.build_run_command is stubbed where needed).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from api.models import ProgressStatus, TaskStatus
from api.services import worktree
from api.services.claude import RunSpec
from api.services.execution import ExecutionManager, SSEBus
from api.storage import StorageService


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def _seed_repo(root: str) -> None:
    _git(["config", "user.email", "t@t.com"], root)
    _git(["config", "user.name", "T"], root)
    (__import__("pathlib").Path(root) / "README.md").write_text("hi\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "init"], root)


# ── worktree helpers ─────────────────────────────────────────────────────────────


def test_worktree_lifecycle(root, tmp_path):
    _seed_repo(root)
    wt = str(tmp_path / "wt")
    branch = worktree.branch_name("my-task", "abcdef12-3456")
    base = worktree.add_worktree(root, wt, branch)
    assert base and len(base) >= 7

    from pathlib import Path
    Path(wt, "new.txt").write_text("change\n")
    assert worktree.has_changes(wt, base)

    sha = worktree.commit_all(wt, "did the thing")
    assert sha and sha != base

    d = worktree.diff(wt, base)
    files = [f["path"] for f in d["files"]]
    assert "new.txt" in files
    assert d["baseSha"] == base

    worktree.remove_worktree(root, wt, branch)
    assert not Path(wt).exists()


def test_sync_worktree_ff_and_conflict(root, tmp_path):
    from pathlib import Path

    _seed_repo(root)
    wt = str(tmp_path / "wt")
    base_branch = worktree.current_branch(root)
    worktree.add_worktree(root, wt, worktree.branch_name("t", "syncid01"), base=base_branch)

    # Base advances with a non-overlapping file -> clean fast-forward into worktree.
    Path(root, "base_only.txt").write_text("from base\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "base advance"], root)
    res = worktree.sync_worktree(wt, base_branch)
    assert res["updated"] and not res["conflicts"]
    assert Path(wt, "base_only.txt").exists()

    # Now both sides edit README differently -> merge conflict surfaced.
    Path(root, "README.md").write_text("base edit\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "base README"], root)
    Path(wt, "README.md").write_text("worktree edit\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-q", "-m", "wt README"], wt)
    res2 = worktree.sync_worktree(wt, base_branch)
    assert res2["updated"] and "README.md" in res2["conflicts"]


def test_diff_includes_untracked_and_nested_repos(root, tmp_path):
    from pathlib import Path

    _seed_repo(root)
    wt = str(tmp_path / "wt")
    base = worktree.add_worktree(root, wt, worktree.branch_name("t", "diffid1"))

    # Untracked new file at the top level (not shown by `git diff <base>`).
    Path(wt, "top_new.txt").write_text("hello\n")

    # A nested git repo inside the worktree with a modified + an untracked file.
    sub = Path(wt, "subproj")
    sub.mkdir()
    _git(["init", "-q"], sub)
    _git(["config", "user.email", "t@t.com"], sub)
    _git(["config", "user.name", "T"], sub)
    Path(sub, "code.py").write_text("x = 1\n")
    _git(["add", "-A"], sub)
    _git(["commit", "-q", "-m", "init"], sub)
    Path(sub, "code.py").write_text("x = 2\n")        # uncommitted change
    Path(sub, "new_in_sub.py").write_text("y = 3\n")  # untracked in the nested repo

    d = worktree.diff(wt, base)
    paths = {f["path"] for f in d["files"]}
    assert "top_new.txt" in paths               # top-level untracked captured
    assert "subproj/code.py" in paths           # nested repo change captured
    assert "subproj/new_in_sub.py" in paths     # nested repo untracked captured
    assert "subproj" not in paths               # the nested repo dir isn't a bare entry


def test_merge_branches_and_branch_exists(root, tmp_path):
    from pathlib import Path

    _seed_repo(root)
    base_branch = worktree.current_branch(root)

    # Two dependency branches off base, each adding a distinct file.
    for name, fname in [("promptly/dep-a", "a.txt"), ("promptly/dep-b", "b.txt")]:
        _git(["checkout", "-q", "-b", name, base_branch], root)
        Path(root, fname).write_text("x\n")
        _git(["add", "-A"], root)
        _git(["commit", "-q", "-m", name], root)
    _git(["checkout", "-q", base_branch], root)

    assert worktree.branch_exists(root, "promptly/dep-a")
    assert not worktree.branch_exists(root, "promptly/missing")

    wt = str(tmp_path / "wt")
    base = worktree.add_worktree(root, wt, worktree.branch_name("t", "mergeid1"), base=base_branch)
    res = worktree.merge_branches(wt, ["promptly/dep-a", "promptly/dep-b"])
    assert res["conflicts"] == [] and len(res["merged"]) == 2
    assert Path(wt, "a.txt").exists() and Path(wt, "b.txt").exists()
    assert worktree.head_sha(wt) != base  # advanced past the original base


def test_merge_branches_reports_conflict(root, tmp_path):
    from pathlib import Path

    _seed_repo(root)
    base_branch = worktree.current_branch(root)
    _git(["checkout", "-q", "-b", "promptly/dep-c", base_branch], root)
    Path(root, "README.md").write_text("dep edit\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "dep README"], root)
    _git(["checkout", "-q", base_branch], root)

    wt = str(tmp_path / "wt")
    worktree.add_worktree(root, wt, worktree.branch_name("t", "conf1"), base=base_branch)
    Path(wt, "README.md").write_text("worktree edit\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-q", "-m", "wt README"], wt)

    res = worktree.merge_branches(wt, ["promptly/dep-c"])
    assert "README.md" in res["conflicts"]


def test_merge_dependency_branches_bases_off_pushed_dep(storage, root, tmp_path):
    """A dependent task whose dependency is in review + pushed gets that dependency's
    branch merged into its worktree, and the diff base advances past it."""
    from pathlib import Path

    _seed_repo(root)
    base_branch = worktree.current_branch(root)
    dep_branch = "promptly/dep-feature"
    _git(["checkout", "-q", "-b", dep_branch, base_branch], root)
    Path(root, "dep_file.txt").write_text("dependency work\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "dep work"], root)
    _git(["checkout", "-q", base_branch], root)

    storage.create_project("Demo", root)
    dep = storage.create_entry(root, "Demo", type="task", display_name="Dep")
    dependent = storage.create_entry(root, "Demo", type="task", display_name="Dependent")
    storage.patch_metadata(root, "Demo", "tasks", dependent.id, {"dependsOn": [dep.id]})
    storage.create_execution(root, "Demo", "depexec", dep.id)
    storage.set_execution_meta(root, "Demo", "depexec", branch=dep_branch, base_sha="x")
    storage.patch_metadata(root, "Demo", "tasks", dep.id, {
        "status": TaskStatus.in_review.value,
        "executionId": "depexec",
        "relatedPrs": [{"url": "http://pr/1", "number": 1, "state": "open"}],
    })

    wt = str(tmp_path / "wt")
    base = worktree.add_worktree(root, wt, worktree.branch_name("dependent", "dep01"), base=base_branch)

    em = ExecutionManager(storage, SSEBus(), claude=None)
    dependent_obj = storage.get_entry(root, "Demo", "tasks", dependent.id)
    prefix, new_base = em._merge_dependency_branches(root, "Demo", dependent_obj, wt, base)

    assert "Dep" in prefix and "in review" in prefix
    assert Path(wt, "dep_file.txt").exists()
    assert new_base != base  # base advanced to the post-merge tip


def test_merge_dependency_branches_skips_unpushed_or_done(storage, root, tmp_path):
    """No merge when the dependency is done (already in base) or in review but not
    pushed (no PR) — base_sha stays put and no prefix is added."""
    _seed_repo(root)
    base_branch = worktree.current_branch(root)
    storage.create_project("Demo", root)
    done = storage.create_entry(root, "Demo", type="task", display_name="Done")
    unpushed = storage.create_entry(root, "Demo", type="task", display_name="Unpushed")
    dependent = storage.create_entry(root, "Demo", type="task", display_name="Dependent")
    storage.patch_metadata(root, "Demo", "tasks", dependent.id,
                           {"dependsOn": [done.id, unpushed.id]})
    storage.patch_metadata(root, "Demo", "tasks", done.id,
                           {"status": TaskStatus.done.value})
    storage.patch_metadata(root, "Demo", "tasks", unpushed.id,
                           {"status": TaskStatus.in_review.value})  # no relatedPrs

    wt = str(tmp_path / "wt")
    base = worktree.add_worktree(root, wt, worktree.branch_name("d", "skip1"), base=base_branch)
    em = ExecutionManager(storage, SSEBus(), claude=None)
    dependent_obj = storage.get_entry(root, "Demo", "tasks", dependent.id)
    prefix, new_base = em._merge_dependency_branches(root, "Demo", dependent_obj, wt, base)
    assert prefix == "" and new_base == base


# ── internal callbacks (MCP server / hook talk back here) ────────────────────────


@pytest.fixture
def engine(storage, root):
    return ExecutionManager(storage, SSEBus(), claude=None)


def test_internal_steps_and_question(storage, root, engine, monkeypatch):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "e1", "t1")

    # seed steps: first is auto in_progress, rest pending
    s = storage.seed_steps(
        root, "Demo", "e1",
        [{"title": "read spec"}, {"title": "write code"}],
    )
    assert [st.title for st in s.steps] == ["read spec", "write code"]
    assert s.steps[0].status == "in_progress" and s.steps[0].started_at
    assert s.steps[1].status == "pending"

    # completing a step auto-advances the next to in_progress
    s = storage.complete_step(root, "Demo", "e1", title="read spec")
    assert s.steps[0].status == "done" and s.steps[0].finished_at
    assert s.steps[1].status == "in_progress"

    # revise: provide the whole list, marking which are done; first not-done -> active
    s = storage.revise_steps(
        root, "Demo", "e1",
        [{"title": "read spec", "done": True},
         {"title": "write code", "done": False},
         {"title": "add tests", "done": False}],
    )
    assert [st.title for st in s.steps] == ["read spec", "write code", "add tests"]
    assert s.steps[0].status == "done"
    assert s.steps[1].status == "in_progress"  # first not-done becomes active
    assert s.steps[2].status == "pending"

    # a question flips status to awaiting_input and is recorded
    s, qobj = storage.add_question(root, "Demo", "e1", "Which DB?")
    assert s.status == ProgressStatus.awaiting_input.value
    assert qobj.answer is None
    s2, ans = storage.answer_question(root, "Demo", "e1", qobj.id, "postgres")
    assert ans.answer == "postgres"


def test_complete_step_fuzzy_and_fallback(storage, root):
    """step_complete must not silently drop a completion when the title doesn't match
    byte-for-byte: it matches fuzzily, and falls back to the active step otherwise."""
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "ef", "tf")
    storage.seed_steps(root, "Demo", "ef",
                       [{"title": "Read the spec"}, {"title": "Write the code"},
                        {"title": "Add tests"}])

    # Fuzzy: numbered prefix + trailing period + casing differences still match.
    s = storage.complete_step(root, "Demo", "ef", title="1. read the spec.")
    assert s.steps[0].status == "done"
    assert s.steps[1].status == "in_progress"

    # Fallback: an unrecognizable title completes the current active step, not nothing.
    s = storage.complete_step(root, "Demo", "ef", title="(some unrelated phrasing)")
    assert s.steps[1].status == "done"
    assert s.steps[2].status == "in_progress"


def test_last_step_complete_finalizes(storage, root, tmp_path):
    """Completing the final step finalizes the task (commit + in_review) with no separate
    `done` command; the optional summary on that step_complete is kept."""
    _seed_repo(root)
    storage.create_project("Demo", root)
    task = storage.create_entry(root, "Demo", type="task", display_name="Fin")
    storage.create_execution(root, "Demo", "efin", task.id)
    from api.storage import paths
    wt = str(paths.worktree_path(root, "Demo", "efin"))
    base = worktree.add_worktree(root, wt, worktree.branch_name("fin", "efin"))
    storage.set_execution_meta(root, "Demo", "efin", base_sha=base)
    storage.seed_steps(root, "Demo", "efin", [{"title": "a"}, {"title": "b"}])

    em = ExecutionManager(storage, SSEBus(), claude=None)
    out = em._handle_command(root, "Demo", "efin", task.id, {"type": "step_complete", "step": 1})
    assert out is not None and "step 2 of 2" in out  # not finalized yet
    out = em._handle_command(root, "Demo", "efin", task.id,
                             {"type": "step_complete", "step": 2, "summary": "all good"})
    assert out is None  # finalized -> loop stops
    prog = storage.read_progress(root, "Demo", "efin")
    assert prog.status == ProgressStatus.completed.value and prog.done_summary == "all good"
    assert storage.get_entry(root, "Demo", "tasks", task.id).status == TaskStatus.in_review.value


def test_complete_step_by_number(storage, root):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "en", "tn")
    storage.seed_steps(root, "Demo", "en", [{"title": "a"}, {"title": "b"}, {"title": "c"}])
    s = storage.complete_step(root, "Demo", "en", number=1)
    assert s.steps[0].status == "done" and s.steps[1].status == "in_progress"
    # an out-of-range number falls back to the active step rather than dropping it
    s = storage.complete_step(root, "Demo", "en", number=99)
    assert s.steps[1].status == "done" and s.steps[2].status == "in_progress"


def test_revise_steps_preserves_done_when_flag_omitted(storage, root):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "er", "tr")
    storage.seed_steps(root, "Demo", "er", [{"title": "a"}, {"title": "b"}])
    storage.complete_step(root, "Demo", "er", title="a")
    # Revise without restating done on the already-done step "a" -> stays done.
    s = storage.revise_steps(root, "Demo", "er",
                             [{"title": "a"}, {"title": "b"}, {"title": "c"}])
    assert s.steps[0].status == "done"
    assert s.steps[1].status == "in_progress"


def test_internal_endpoints_require_token(storage, root):
    from fastapi.testclient import TestClient

    from api.deps import get_storage
    from api.main import create_app

    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "e2", "t2")

    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    client = TestClient(app, raise_server_exceptions=False)

    # wrong token -> 403 (permission-request is the one remaining internal endpoint)
    r = client.post("/internal/executions/e2/permission-request", params={"project": "Demo"},
                    headers={"X-Promptly-Token": "nope"}, json={"tool": "Write"})
    assert r.status_code == 403


# ── run loop finalize ────────────────────────────────────────────────────────────


async def test_run_loop_completes_and_commits(storage, root, tmp_path, monkeypatch):
    _seed_repo(root)
    storage.create_project("Demo", root)
    task = storage.create_entry(root, "Demo", type="task", display_name="Build it")
    storage.create_execution(root, "Demo", "e3", task.id)

    # real worktree so _complete can commit
    from api.storage import paths
    wt = str(paths.worktree_path(root, "Demo", "e3"))
    base = worktree.add_worktree(root, wt, worktree.branch_name("build-it", "e3"))
    storage.set_execution_meta(root, "Demo", "e3", base_sha=base)

    em = ExecutionManager(storage, SSEBus(), claude=None)

    # Fake one CLI turn: emit a stream-json init line (session id) + a result event
    # carrying a `done` structured-output command, then exit 0. No steps seeded, so
    # `done` finalizes immediately.
    fake = (
        "import json; "
        "print(json.dumps({'type':'system','subtype':'init','session_id':'sess-9'})); "
        "print(json.dumps({'type':'result','session_id':'sess-9',"
        "'structured_output':{'type':'done','summary':'all done'}}))"
    )

    class FakeClaude:
        def build_run_command(self, root, project, *, execution_id, worktree,
                              prompt, session_id=None, granted=None):
            return RunSpec(args=[sys.executable, "-c", fake],
                           env=dict(__import__("os").environ), cwd=worktree)

    em.claude = FakeClaude()
    await em._run(root, "Demo", "e3", task.id, "prompt")

    prog = storage.read_progress(root, "Demo", "e3")
    assert prog.status == ProgressStatus.completed.value
    assert prog.session_id == "sess-9"
    assert prog.done_summary == "all done"
    refreshed = storage.get_entry(root, "Demo", "tasks", task.id)
    assert refreshed.status == TaskStatus.in_review.value


async def test_run_loop_handles_oversized_line(storage, root, tmp_path):
    """A single stream-json line larger than asyncio's default readline cap (64 KiB)
    must not crash the turn (regression: 'Separator is not found, chunk exceeded')."""
    _seed_repo(root)
    storage.create_project("Demo", root)
    task = storage.create_entry(root, "Demo", type="task", display_name="Big")
    storage.create_execution(root, "Demo", "e5", task.id)
    from api.storage import paths
    wt = str(paths.worktree_path(root, "Demo", "e5"))
    base = worktree.add_worktree(root, wt, worktree.branch_name("big", "e5"))
    storage.set_execution_meta(root, "Demo", "e5", base_sha=base)

    em = ExecutionManager(storage, SSEBus(), claude=None)
    # ~200 KB assistant text line, then the done command.
    fake = (
        "import json; "
        "print(json.dumps({'type':'assistant','session_id':'sess-big',"
        "'message':{'content':[{'type':'text','text':'A'*200000}]}})); "
        "print(json.dumps({'type':'result','session_id':'sess-big',"
        "'structured_output':{'type':'done','summary':'ok'}}))"
    )

    class FakeClaude:
        def build_run_command(self, root, project, *, execution_id, worktree,
                              prompt, session_id=None, granted=None):
            return RunSpec(args=[sys.executable, "-c", fake],
                           env=dict(__import__("os").environ), cwd=worktree)

    em.claude = FakeClaude()
    await em._run(root, "Demo", "e5", task.id, "prompt")

    prog = storage.read_progress(root, "Demo", "e5")
    assert prog.status == ProgressStatus.completed.value
    assert prog.session_id == "sess-big"


async def test_run_loop_failure(storage, root, tmp_path):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "e4", "t4")
    em = ExecutionManager(storage, SSEBus(), claude=None)

    class FakeClaude:
        def build_run_command(self, *a, worktree="", **k):
            return RunSpec(args=[sys.executable, "-c",
                                 "import sys; sys.stderr.write('boom'); sys.exit(1)"],
                           env=dict(__import__("os").environ), cwd=str(tmp_path))

    em.claude = FakeClaude()
    await em._run(root, "Demo", "e4", "t4", "prompt")
    prog = storage.read_progress(root, "Demo", "e4")
    assert prog.status == ProgressStatus.failed.value
    assert "boom" in (prog.error or "")


# ── resume control flow (no real subprocess) ─────────────────────────────────────


async def test_answer_resumes_with_session(storage, root, monkeypatch):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "e5", "t5")
    storage.set_execution_meta(root, "Demo", "e5", session_id="sess-A")
    _, q = storage.add_question(root, "Demo", "e5", "Which framework?")

    em = ExecutionManager(storage, SSEBus(), claude=None)
    calls = {}

    async def fake_run(root, project, eid, task_id, prompt, *, session_id=None):
        calls.update(prompt=prompt, session_id=session_id, eid=eid)

    monkeypatch.setattr(em, "_run", fake_run)
    monkeypatch.setattr(em, "_sync_for_resume", lambda *a: "")  # git sync tested elsewhere
    await em.answer(root, "Demo", "e5", q.id, "FastAPI")
    # the spawned task runs on the loop; let it execute
    import asyncio
    await asyncio.sleep(0)

    assert calls["session_id"] == "sess-A"
    assert "FastAPI" in calls["prompt"]
    prog = storage.read_progress(root, "Demo", "e5")
    assert prog.pending_questions[0].answer == "FastAPI"


async def test_permission_allow_resumes_with_grant(storage, root, monkeypatch):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "e6", "t6")
    storage.set_execution_meta(root, "Demo", "e6", session_id="sess-B")
    _, pr = storage.add_permission_request(root, "Demo", "e6", "Bash",
                                           {"command": "rm -rf build"})

    em = ExecutionManager(storage, SSEBus(), claude=None)
    captured = {}

    async def fake_run(root, project, eid, task_id, prompt, *, session_id=None):
        # _run reads granted from progress; verify the decision stuck
        prog = storage.read_progress(root, project, eid)
        captured["granted"] = [p.request["command"] for p in prog.pending_permissions
                               if p.decision == "allow"]
        captured["prompt"] = prompt

    monkeypatch.setattr(em, "_run", fake_run)
    monkeypatch.setattr(em, "_sync_for_resume", lambda *a: "")  # git sync tested elsewhere
    await em.decide_permission(root, "Demo", "e6", pr.id, "allow")
    import asyncio
    await asyncio.sleep(0)

    assert captured["granted"] == ["rm -rf build"]
    assert "approved" in captured["prompt"].lower()


async def test_resume_continues_with_session(storage, root, monkeypatch):
    storage.create_project("Demo", root)
    task = storage.create_entry(root, "Demo", type="task", display_name="T8")
    storage.create_execution(root, "Demo", "e8", task.id)
    storage.set_execution_meta(root, "Demo", "e8", session_id="sess-D")
    # in an error state with the task flagged
    storage.set_execution_status(root, "Demo", "e8", ProgressStatus.failed, error="boom")
    storage.patch_metadata(root, "Demo", "tasks", task.id, {"executionError": True})

    em = ExecutionManager(storage, SSEBus(), claude=None)
    calls = {}

    async def fake_run(root, project, eid, task_id, prompt, *, session_id=None):
        calls.update(prompt=prompt, session_id=session_id, eid=eid)

    monkeypatch.setattr(em, "_run", fake_run)
    monkeypatch.setattr(em, "_sync_for_resume", lambda *a: "")
    monkeypatch.setattr("api.services.execution.read_transcript_command", lambda sid: None)
    await em.resume(root, "Demo", "e8")
    import asyncio
    await asyncio.sleep(0)

    assert calls["session_id"] == "sess-D" and calls["eid"] == "e8"
    assert "continue" in calls["prompt"].lower()
    # the task error flag is cleared on resume
    assert storage.get_entry(root, "Demo", "tasks", task.id).execution_error is False


async def test_resume_pauses_on_transcript_question(storage, root, monkeypatch):
    storage.create_project("Demo", root)
    storage.create_execution(root, "Demo", "e8b", "t8b")
    storage.set_execution_meta(root, "Demo", "e8b", session_id="sess-Q")
    storage.set_execution_status(root, "Demo", "e8b", ProgressStatus.failed, error="boom")

    em = ExecutionManager(storage, SSEBus(), claude=None)
    called = {"run": False}

    async def fake_run(*a, **k):
        called["run"] = True

    monkeypatch.setattr(em, "_run", fake_run)
    # the transcript shows the run ended on a question -> resume should pause, not re-run
    monkeypatch.setattr("api.services.execution.read_transcript_command",
                        lambda sid: {"type": "question", "question": "Which DB?"})
    state = await em.resume(root, "Demo", "e8b")

    assert called["run"] is False
    assert state.status == ProgressStatus.awaiting_input.value
    assert state.pending_questions[-1].question == "Which DB?"


def test_mark_orphans_interrupted(storage, root):
    storage.create_project("Demo", root)
    task = storage.create_entry(root, "Demo", type="task", display_name="Orphan")
    storage.create_execution(root, "Demo", "e9", task.id)
    storage.set_execution_meta(root, "Demo", "e9", session_id="sess-Z")
    storage.set_execution_status(root, "Demo", "e9", ProgressStatus.running)

    em = ExecutionManager(storage, SSEBus(), claude=None)
    em.mark_orphans_interrupted()

    prog = storage.read_progress(root, "Demo", "e9")
    assert prog.status == ProgressStatus.failed.value
    assert prog.session_id == "sess-Z"  # session kept for Try again
    assert "interrupted" in (prog.error or "").lower()
    assert storage.get_entry(root, "Demo", "tasks", task.id).execution_error is True


# ── build_run_command shape (no CLI spawned) ─────────────────────────────────────


def test_build_run_command_scoped_default(storage, root):
    """Default profile: auto mode (no prompts) WITH explicit scoping — reads confined
    to the worktree (no add-dir), writes gated to the worktree by the hook (deny)."""
    from api.services.claude import ClaudeService

    storage.create_project("Demo", root)
    claude = ClaudeService(storage, internal_token="secret-tok",
                           api_url="http://127.0.0.1:8000")
    spec = claude.build_run_command(
        root, "Demo", execution_id="e9", worktree="/tmp/wt", prompt="go", session_id="sess-Z",
    )
    args = spec.args
    assert "stream-json" in args
    assert "--resume" in args and "sess-Z" in args
    assert "auto" in args  # unattended, no prompts

    # Progress is via --json-schema structured output, not MCP.
    assert "--json-schema" in args
    assert "--mcp-config" not in args and "--strict-mcp-config" not in args

    # read scope = the worktree (cwd) only — no --add-dir of repo/project/docs/tasks
    add_dirs = [args[i + 1] for i, a in enumerate(args) if a == "--add-dir"]
    assert add_dirs == []

    settings = json.loads(args[args.index("--settings") + 1])
    assert settings["permissions"]["additionalDirectories"] == []
    assert "PreToolUse" in settings["hooks"]  # write boundary even under auto
    assert settings["hooks"]["PreToolUse"][0]["matcher"] == "Write|Edit|MultiEdit|NotebookEdit"
    assert "Bash" in settings["permissions"]["allow"]  # bash runs unattended
    assert spec.env["PROMPTLY_HOOK_MODE"] == "deny"
    assert spec.env["PROMPTLY_WORKTREE"] == "/tmp/wt"


def test_build_run_command_bypass_drops_hook(storage, root):
    """permissionMode 'bypassPermissions' = fully unscoped, no hook."""
    from api.models import PermissionsConfig, PermissionProfile
    from api.services.claude import ClaudeService

    storage.create_project("Demo", root)
    cfg = PermissionsConfig()
    cfg.execution = PermissionProfile(permission_mode="bypassPermissions",
                                      allow=["Read", "Edit", "Write", "Bash"])
    storage.write_permissions(root, "Demo", cfg)

    claude = ClaudeService(storage, internal_token="t", api_url="http://127.0.0.1:8000")
    spec = claude.build_run_command(
        root, "Demo", execution_id="e9", worktree="/tmp/wt", prompt="go",
    )
    args = spec.args
    assert "bypassPermissions" in args
    settings = json.loads(args[args.index("--settings") + 1])
    assert "hooks" not in settings
    assert "PROMPTLY_HOOK_MODE" not in spec.env


def test_build_run_command_ask_mode_forwards_grants(storage, root):
    """ask_fallback profile: hook in ask mode, granted edit paths -> --allowedTools."""
    from api.models import PermissionRequest, PermissionsConfig, PermissionProfile
    from api.services.claude import ClaudeService

    storage.create_project("Demo", root)
    cfg = PermissionsConfig()
    cfg.execution = PermissionProfile(permission_mode="default",
                                      allow=["Read", "Grep", "Glob", "Bash"],
                                      ask_fallback=True)
    storage.write_permissions(root, "Demo", cfg)

    claude = ClaudeService(storage, internal_token="t", api_url="http://127.0.0.1:8000")
    granted = [PermissionRequest(id="p1", tool="Write",
                                 request={"path": "/etc/thing"}, asked_at="now")]
    spec = claude.build_run_command(
        root, "Demo", execution_id="e9", worktree="/tmp/wt", prompt="go", granted=granted,
    )
    args = spec.args
    assert "PreToolUse" in json.loads(args[args.index("--settings") + 1])["hooks"]
    assert "Write(/etc/thing)" in args
    assert spec.env["PROMPTLY_HOOK_MODE"] == "ask"
    assert "/etc/thing" in json.loads(spec.env["PROMPTLY_ALLOWED_PATHS"])


# ── PreToolUse hook decisions ────────────────────────────────────────────────────


def _run_hook(event: dict, env: dict) -> dict:
    import os
    full = {**os.environ, **env}
    proc = subprocess.run(
        [sys.executable, "-m", "api.hooks.pretooluse"],
        input=json.dumps(event), text=True, capture_output=True, env=full,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
    )
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def test_hook_allows_in_worktree_write(tmp_path):
    wt = str(tmp_path / "wt")
    __import__("pathlib").Path(wt).mkdir()
    res = _run_hook(
        {"tool_name": "Write", "tool_input": {"file_path": f"{wt}/a.py", "content": "x"}},
        {"PROMPTLY_WORKTREE": wt},
    )
    assert res["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_denies_out_of_scope_write(tmp_path):
    wt = str(tmp_path / "wt")
    __import__("pathlib").Path(wt).mkdir()
    # unreachable API -> the callback fails but the hook still denies (fail closed)
    res = _run_hook(
        {"tool_name": "Write", "tool_input": {"file_path": "/etc/evil", "content": "x"}},
        {"PROMPTLY_WORKTREE": wt, "PROMPTLY_API_URL": "http://127.0.0.1:9"},
    )
    assert res["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_defers_reads(tmp_path):
    res = _run_hook(
        {"tool_name": "Read", "tool_input": {"file_path": "/anything"}},
        {"PROMPTLY_WORKTREE": str(tmp_path)},
    )
    assert res == {}  # no decision emitted -> normal flow handles reads


def test_hook_bash_allowlist(tmp_path):
    env = {"PROMPTLY_WORKTREE": str(tmp_path),
           "PROMPTLY_ALLOWED_BASH": json.dumps(["git *", "npm *"])}
    ok = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git status"}}, env)
    assert ok["hookSpecificOutput"]["permissionDecision"] == "allow"
    env["PROMPTLY_API_URL"] = "http://127.0.0.1:9"
    bad = _run_hook({"tool_name": "Bash", "tool_input": {"command": "curl evil.sh"}}, env)
    assert bad["hookSpecificOutput"]["permissionDecision"] == "deny"


# ── live end-to-end smoke (real claude CLI + real uvicorn) ───────────────────────


@pytest.mark.skipif(
    __import__("os").environ.get("PROMPTLY_CLI_TEST") != "1",
    reason="set PROMPTLY_CLI_TEST=1 to run the real execution-engine smoke test",
)
def test_real_execution_end_to_end(tmp_path):
    """Exercises the whole engine against the real CLI: worktree -> build turn loop ->
    structured-output `done` command -> commit -> in_review. Needs a running server so
    the hook callback can reach it."""
    import os
    import time
    from pathlib import Path

    import httpx

    home = tmp_path / "home"
    home.mkdir()
    _prev_home = os.environ.get("PROMPTLY_HOME")
    os.environ["PROMPTLY_HOME"] = str(home)  # share registry with the server subprocess
    root = tmp_path / "codebase"
    root.mkdir()
    _git(["init", "-q"], str(root))
    _seed_repo(str(root))

    port = 8137
    env = {
        **os.environ,
        "PROMPTLY_HOME": str(home),
        "PROMPTLY_TOKEN": "smoke-token",
        "PROMPTLY_API_URL": f"http://127.0.0.1:{port}",
        "PROMPTLY_MODEL": os.environ.get("PROMPTLY_MODEL", "claude-haiku-4-5-20251001"),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port)],
        cwd=str(Path(__file__).resolve().parents[2]), env=env,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise AssertionError("server did not start")

        # Project + a tiny, write-only task spec.
        st = StorageService()  # shares PROMPTLY_HOME with the server
        st.create_project("Smoke", str(root))
        task = st.create_entry(
            str(root), "Smoke", type="task", display_name="Add hello file",
            description="create hello.txt",
            body="# Add hello file\n\nCreate a file named `hello.txt` at the repo "
                 "root containing exactly the text `hello world`. Nothing else.",
        )

        q = {"project": "Smoke"}
        r = httpx.post(f"{base}/executions", params=q,
                       json={"taskId": task.id}, timeout=30)
        assert r.status_code == 201, r.text
        eid = r.json()["executionId"]

        deadline = time.time() + 300
        status = None
        while time.time() < deadline:
            prog = httpx.get(f"{base}/executions/{eid}", params=q, timeout=10).json()
            status = prog["status"]
            if status in ("completed", "failed"):
                break
            if status == "awaiting_input":
                # Approve any out-of-scope action / answer any question, then resume.
                for p in prog["pendingPermissions"]:
                    if p["decision"] is None:
                        httpx.post(f"{base}/executions/{eid}/permission", params=q,
                                   json={"requestId": p["id"], "decision": "allow"},
                                   timeout=30)
                for question in prog["pendingQuestions"]:
                    if question["answer"] is None:
                        httpx.post(f"{base}/executions/{eid}/answer", params=q,
                                   json={"questionId": question["id"],
                                         "answer": "Use the Write tool to create the file."},
                                   timeout=30)
            time.sleep(2)
        assert status == "completed", f"ended {status}: {prog.get('error')}"

        # Task moved to review, worktree has the file committed.
        doc = httpx.get(f"{base}/tasks/{task.id}", params=q, timeout=10).json()
        assert doc["meta"]["status"] == "in_review"
        diff = httpx.get(f"{base}/executions/{eid}/diff", params=q, timeout=10).json()
        assert any(f["path"] == "hello.txt" for f in diff["files"])
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        if _prev_home is None:
            os.environ.pop("PROMPTLY_HOME", None)
        else:
            os.environ["PROMPTLY_HOME"] = _prev_home
