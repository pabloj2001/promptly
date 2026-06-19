"""OperationManager: bus → SSE stream delivery, and the async run lifecycle."""

import asyncio

import pytest

from api.models import DocType
from api.services.operations import OperationManager


class StubClaude:
    """Deterministic stand-in for ClaudeService (no real CLI)."""

    async def generate_document(self, *, root, project, prompt, type, depends_on=None,
                                name_hint=None):
        from api.services.claude import GeneratedDoc
        return GeneratedDoc(name=name_hint or "Gen", description="d", body="# Gen\nbody")

    async def infer_target_repo(self, *, root, project, body, repos):
        # Prove inference is wired: pick the first non-primary repo when present.
        nonprimary = [r for r in repos if not r.primary]
        return nonprimary[0].id if nonprimary else repos[0].id


@pytest.mark.asyncio
async def test_stream_delivers_published_event(storage):
    om = OperationManager(storage, StubClaude())
    agen = om.stream("proj")
    nxt = asyncio.create_task(agen.__anext__())
    await asyncio.sleep(0)  # let the subscriber register
    om._publish("proj", "e1", "docs", "generate", "completed")
    msg = await asyncio.wait_for(nxt, 1)
    assert msg["event"] == "operation"
    assert msg["data"] == {
        "entryId": "e1", "collection": "docs",
        "type": "generate", "status": "completed", "error": None,
    }
    await agen.aclose()


@pytest.mark.asyncio
async def test_run_generation_finalizes_and_publishes(storage, project):
    name, root = project
    om = OperationManager(storage, StubClaude())
    ph = storage.create_placeholder(root, name, type=DocType.task,
                                    provisional_name="Temp")
    assert ph.operation.status == "running"

    agen = om.stream(name)
    nxt = asyncio.create_task(agen.__anext__())
    await asyncio.sleep(0)

    om.start_generation(root, name, ph.id, "tasks",
                        prompt="x", type=DocType.task, depends_on=[], name_hint=None)
    msg = await asyncio.wait_for(nxt, 5)
    assert msg["data"]["status"] == "completed"

    entry = storage.get_entry(root, name, "tasks", ph.id)
    assert entry.operation is None          # cleared
    assert entry.name == "Gen"              # finalized from generation
    _, body, _ = storage.read_document(root, name, "tasks", ph.id)
    assert "body" in body
    await agen.aclose()


@pytest.mark.asyncio
async def test_run_generation_infers_repo_when_multi_repo(storage, project):
    from api.models import ProjectRepo, ProjectRepos

    name, root = project
    storage.write_repos(root, name, ProjectRepos(repos=[
        ProjectRepo(id="primary", name="main", primary=True),
        ProjectRepo(id="", name="docs", url="https://example.com/docs.git"),
    ]))
    om = OperationManager(storage, StubClaude())
    ph = storage.create_placeholder(root, name, type=DocType.task, provisional_name="T")

    om.start_generation(root, name, ph.id, "tasks",
                        prompt="x", type=DocType.task, depends_on=[], name_hint=None)
    for _ in range(50):  # let the background task finish
        await asyncio.sleep(0.01)
        if storage.get_entry(root, name, "tasks", ph.id).operation is None:
            break

    entry = storage.get_entry(root, name, "tasks", ph.id)
    repos = storage.read_repos(root, name).repos
    nonprimary = next(r for r in repos if not r.primary)
    assert entry.repo == nonprimary.id  # AI-inferred target repo applied
