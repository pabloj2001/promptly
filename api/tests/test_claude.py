import os

import pytest

from api.models import DocType
from api.services.claude import (
    ChatTurn,
    ClaudeError,
    ClaudeService,
    GenResult,
    _parse_structured,
    _strip_fences,
)


# ── pure parsing helpers ─────────────────────────────────────────────────────────


def test_strip_fences_json_block():
    assert _strip_fences('```json\n{"a":1}\n```').strip() == '{"a":1}'


def test_parse_structured_clean():
    obj = _parse_structured('{"name":"N","description":"D","body":"# B"}')
    assert obj["name"] == "N" and obj["body"] == "# B"


def test_parse_structured_with_prose_around():
    text = 'Here you go:\n{"name":"N","description":"D","body":"B"}\nHope that helps!'
    assert _parse_structured(text)["body"] == "B"


def test_parse_structured_require_key():
    assert _parse_structured('{"reply":"hi"}', require="reply")["reply"] == "hi"
    assert _parse_structured('{"reply":"hi"}', require="body") is None


def test_parse_structured_garbage_returns_none():
    assert _parse_structured("not json at all") is None


# ── generation (CLI mocked) ──────────────────────────────────────────────────────


@pytest.fixture
def svc(storage):
    return ClaudeService(storage)


@pytest.mark.asyncio
async def test_generate_document_parses_result(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        # sanity: generation runs at repo root with a settings payload
        assert kw["cwd"] == root
        assert kw["settings_json"]
        return GenResult(
            text='{"name":"Auth Spec","description":"login","body":"# Auth\\nbody"}',
            session_id="s1",
        )

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    gen = await svc.generate_document(
        root=root, project=name, prompt="design auth", type=DocType.task,
    )
    assert gen.name == "Auth Spec"
    assert gen.body.startswith("# Auth")


@pytest.mark.asyncio
async def test_generate_document_falls_back_to_raw(svc, project, monkeypatch):
    """Non-JSON output → retry, then graceful fallback (raw text as body)."""
    name, root = project
    calls = {"n": 0}

    async def fake_invoke(prompt, **kw):
        calls["n"] += 1
        return GenResult(text="# My Doc\n\nSome prose, not JSON.")

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    gen = await svc.generate_document(root=root, project=name, prompt="x", type=DocType.doc)
    assert calls["n"] == 2  # initial + one retry before fallback
    assert gen.name == "My Doc"
    assert "Some prose" in gen.body


@pytest.mark.asyncio
async def test_generate_document_raises_on_empty(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(text="   ")

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    with pytest.raises(ClaudeError):
        await svc.generate_document(root=root, project=name, prompt="x", type=DocType.doc)


@pytest.mark.asyncio
async def test_derive_import_metadata_parses(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        assert kw["cwd"] == root  # generation profile (repo-root reads)
        return GenResult(text='{"description":"A login task","taskGroup":"Backend"}')

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    meta = await svc.derive_import_metadata(
        root=root, project=name, body="# Auth\nstuff", doc_type=DocType.task,
    )
    assert meta == {"description": "A login task", "task_group": "Backend"}


@pytest.mark.asyncio
async def test_derive_import_metadata_falls_back(svc, project, monkeypatch):
    """Unparseable output → heuristic description, empty group."""
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(text="sorry, no json here")

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    meta = await svc.derive_import_metadata(
        root=root, project=name, body="# Title\nFirst line summary.", doc_type=DocType.doc,
    )
    assert meta["description"] == "First line summary."
    assert meta["task_group"] == ""


@pytest.mark.asyncio
async def test_plan_execution_steps_structured(svc, project, monkeypatch):
    name, root = project

    async def fake_structured(prompt, *, schema, on_event=None, **kw):
        assert schema.get("required") == ["steps"]  # PLAN_SCHEMA
        if on_event:  # streams its line-of-thinking
            on_event({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Reading the spec"}]}})
        return {"structured_output": {"steps": [
            {"title": "Research", "detail": "look at X"}, {"title": "Implement"}]}}

    monkeypatch.setattr(svc, "_invoke_structured", fake_structured)
    seen = []
    stubs = await svc.plan_execution_steps(
        root=root, project=name, task_name="T", task_file="tasks/none.md",
        dependency_names=[], on_event=lambda e: seen.append(e))

    assert [s.title for s in stubs] == ["Research", "Implement"]
    assert stubs[0].detail == "look at X"
    assert seen  # activity events were forwarded


@pytest.mark.asyncio
async def test_plan_execution_steps_empty_raises(svc, project, monkeypatch):
    from api.services.claude import ClaudeError
    name, root = project

    async def fake_structured(prompt, *, schema, on_event=None, **kw):
        return {"structured_output": {"steps": []}}

    monkeypatch.setattr(svc, "_invoke_structured", fake_structured)
    with pytest.raises(ClaudeError):
        await svc.plan_execution_steps(
            root=root, project=name, task_name="T", task_file="tasks/none.md",
            dependency_names=[])


@pytest.mark.asyncio
async def test_name_hint_overrides(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(text='{"name":"Model","description":"d","body":"b"}')

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    gen = await svc.generate_document(root=root, project=name, prompt="x",
                                      type=DocType.doc, name_hint="My Title")
    assert gen.name == "My Title"


@pytest.mark.asyncio
async def test_chat_returns_turn_with_revision(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(
            text='{"reply":"trimmed it","revisedBody":"# New\\nshort"}',
            session_id="sess-2",
        )

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    turn: ChatTurn = await svc.chat(
        root=root, project=name, doc_type=DocType.doc, body="old", message="trim",
    )
    assert turn.reply == "trimmed it"
    assert turn.revised_body == "# New\nshort"
    assert turn.session_id == "sess-2"


@pytest.mark.asyncio
async def test_chat_plain_reply_no_revision(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(text="just a plain answer, no json")

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    turn = await svc.chat(root=root, project=name, doc_type="doc", body="b", message="?")
    assert "plain answer" in turn.reply
    assert turn.revised_body is None


@pytest.mark.asyncio
async def test_address_comments_strips_fences(svc, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(text="```markdown\n# Revised\nfixed\n```")

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    out = await svc.address_comments(root=root, project=name, body="orig", comments=[])
    assert out == "# Revised\nfixed"


# ── real CLI smoke test (gated) ──────────────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("PROMPTLY_CLI_TEST") != "1",
    reason="set PROMPTLY_CLI_TEST=1 to run the real Claude CLI smoke test",
)
@pytest.mark.asyncio
async def test_real_cli_generation(svc, project):
    name, root = project
    gen = await svc.generate_document(
        root=root, project=name,
        prompt="A one-paragraph doc explaining what a semaphore is.",
        type=DocType.doc,
    )
    assert gen.body and gen.name


@pytest.mark.skipif(
    os.environ.get("PROMPTLY_CLI_TEST") != "1",
    reason="set PROMPTLY_CLI_TEST=1 to run the real Claude CLI smoke test",
)
@pytest.mark.asyncio
async def test_real_cli_plan_tasks(svc, storage, project):
    name, root = project
    storage.create_entry(
        root, name, type=DocType.project_spec, display_name="Spec",
        body="# Todo App\nA CLI todo app with add, list, complete, and delete "
             "commands, storing tasks in a JSON file.",
    )
    stubs = await svc.plan_tasks(root=root, project=name)
    assert len(stubs) >= 2
    assert all(s.name for s in stubs)
