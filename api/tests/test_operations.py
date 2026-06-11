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
