"""ExecutionManager + SSE bus (07).

Feature 02 owns the SSE plumbing (the in-memory pub/sub keyed by execution id and
the snapshot-on-connect contract). The run loop, worktree handling, and resume
paths are stubbed here and implemented in feature 07.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator

from ..models import ProgressState
from ..storage import StorageService


class SSEBus:
    """In-memory pub/sub keyed by execution id. Each subscriber gets its own
    asyncio queue; publishers fan out to all subscribers for that id."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, execution_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[execution_id].add(q)
        return q

    def unsubscribe(self, execution_id: str, q: asyncio.Queue) -> None:
        self._subs[execution_id].discard(q)
        if not self._subs[execution_id]:
            self._subs.pop(execution_id, None)

    def publish(self, execution_id: str, event: str, data: dict) -> None:
        for q in self._subs.get(execution_id, set()):
            q.put_nowait({"event": event, "data": data})


class ExecutionManager:
    def __init__(self, storage: StorageService, bus: SSEBus | None = None) -> None:
        self.storage = storage
        self.bus = bus or SSEBus()

    async def start(self, root: str, project: str, task_id: str) -> ProgressState:
        raise NotImplementedError("ExecutionManager.start — feature 07")

    async def answer(self, root: str, project: str, execution_id: str,
                     question_id: str, answer: str) -> ProgressState:
        raise NotImplementedError("ExecutionManager.answer — feature 07")

    async def decide_permission(self, root: str, project: str, execution_id: str,
                                request_id: str, decision: str) -> ProgressState:
        raise NotImplementedError("ExecutionManager.decide_permission — feature 07")

    async def feedback(self, root: str, project: str, execution_id: str,
                       message: str) -> ProgressState:
        raise NotImplementedError("ExecutionManager.feedback — feature 07")

    async def create_pr(self, root: str, project: str, execution_id: str) -> dict:
        raise NotImplementedError("ExecutionManager.create_pr — feature 07")

    async def diff(self, root: str, project: str, execution_id: str) -> dict:
        raise NotImplementedError("ExecutionManager.diff — feature 07")

    async def stream(self, root: str, project: str, execution_id: str) -> AsyncIterator[dict]:
        """SSE generator: replay the current progress snapshot, then live events.
        Survives reconnects because state always lives in progress.json (07)."""
        snapshot = self.storage.read_progress(root, project, execution_id)
        if snapshot is not None:
            yield {"event": "snapshot", "data": snapshot.model_dump(by_alias=True)}
        q = self.bus.subscribe(execution_id)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            self.bus.unsubscribe(execution_id, q)
