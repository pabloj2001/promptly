import os

import pytest

from api.models import DocType
from api.services.claude import (
    ClaudeService,
    GenResult,
    _parse_structured,
    _strip_fences,
)


# ── pure parsing helpers ─────────────────────────────────────────────────────────


def test_strip_fences_plain():
    assert _strip_fences("hello") == "hello"


def test_strip_fences_json_block():
    assert _strip_fences('```json\n{"a":1}\n```').strip() == '{"a":1}'


def test_parse_structured_clean():
    obj = _parse_structured('{"name":"N","description":"D","body":"# B"}')
    assert obj["name"] == "N" and obj["body"] == "# B"


def test_parse_structured_fenced():
    obj = _parse_structured('```json\n{"name":"N","description":"D","body":"B"}\n```')
    assert obj["body"] == "B"


def test_parse_structured_with_prose_around():
    text = 'Here you go:\n{"name":"N","description":"D","body":"B"}\nHope that helps!'
    obj = _parse_structured(text)
    assert obj["body"] == "B"


def test_parse_structured_garbage_returns_none():
    assert _parse_structured("not json at all") is None


# ── context inlining ─────────────────────────────────────────────────────────────


@pytest.fixture
def svc(storage):
    return ClaudeService(storage)


def test_build_context_includes_spec_manifest_deps(svc, storage, project):
    name, root = project
    storage.create_entry(root, name, type=DocType.project_spec,
                         display_name="Spec", body="# The Spec\nbuild stuff")
    dep = storage.create_entry(root, name, type=DocType.task, display_name="Base",
                               description="base task", body="# Base\ndo base")
    storage.create_entry(root, name, type=DocType.doc, display_name="Notes",
                         description="some notes", body="# Notes")

    ctx = svc.build_context(root, name, dependency_ids=[dep.id])
    assert "The Spec" in ctx                 # full project.md body
    assert "(doc) Notes: some notes" in ctx  # manifest
    assert "(task, pending) Base" in ctx     # manifest task line
    assert "do base" in ctx                  # dependency body inlined
    assert "<project_context>" in ctx


def test_build_context_empty_project(svc, project):
    name, root = project
    assert svc.build_context(root, name) == ""


# ── generation (CLI mocked) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_document_parses_result(svc, storage, project, monkeypatch):
    name, root = project

    async def fake_invoke(prompt, **kw):
        return GenResult(
            text='{"name":"Auth Spec","description":"login","body":"# Auth\\nbody"}',
            session_id="s1", cost=0.01,
        )

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    gen = await svc.generate_document(
        root=root, project=name, prompt="design auth", type=DocType.task,
    )
    assert gen.name == "Auth Spec"
    assert gen.body.startswith("# Auth")


@pytest.mark.asyncio
async def test_generate_document_retries_then_raises(svc, project, monkeypatch):
    name, root = project
    calls = {"n": 0}

    async def fake_invoke(prompt, **kw):
        calls["n"] += 1
        return GenResult(text="totally not json")

    monkeypatch.setattr(svc, "_invoke", fake_invoke)
    from api.services.claude import ClaudeError

    with pytest.raises(ClaudeError):
        await svc.generate_document(root=root, project=name, prompt="x",
                                    type=DocType.doc)
    assert calls["n"] == 2  # initial + one retry


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
