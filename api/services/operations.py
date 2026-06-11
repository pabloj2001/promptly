"""OperationManager — runs async AI authoring operations (03/05).

Doc/task generation and chat edits are slow, so the API returns immediately and the work
runs here as a background asyncio task. Each operation's lifecycle is broadcast over a
per-project SSE bus so the Design tab can show/clear loading states (01/02/05).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from ..models import DocType
from ..storage import StorageService
from .claude import ClaudeService
from .execution import SSEBus


class OperationManager:
    def __init__(self, storage: StorageService, claude: ClaudeService,
                 bus: SSEBus | None = None) -> None:
        self.storage = storage
        self.claude = claude
        self.bus = bus or SSEBus()
        self._tasks: set[asyncio.Task] = set()

    # ── task plumbing ─────────────────────────────────────────────────────────────

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _publish(self, project: str, entry_id: str, collection: str,
                 op_type: str, status: str, error: Optional[str] = None) -> None:
        self.bus.publish(project, "operation", {
            "entryId": entry_id, "collection": collection,
            "type": op_type, "status": status, "error": error,
        })

    async def stream(self, project: str) -> AsyncIterator[dict]:
        q = self.bus.subscribe(project)
        try:
            while True:
                yield await q.get()
        finally:
            self.bus.unsubscribe(project, q)

    # ── generation ────────────────────────────────────────────────────────────────

    def start_generation(self, root: str, project: str, entry_id: str, collection: str,
                         *, prompt: str, type: DocType, depends_on: list[str],
                         name_hint: Optional[str]) -> None:
        self._spawn(self._run_generation(
            root, project, entry_id, collection,
            prompt=prompt, type=type, depends_on=depends_on, name_hint=name_hint,
        ))

    async def _run_generation(self, root: str, project: str, entry_id: str, collection: str,
                              *, prompt, type, depends_on, name_hint) -> None:
        try:
            gen = await self.claude.generate_document(
                root=root, project=project, prompt=prompt, type=type,
                depends_on=depends_on, name_hint=name_hint,
            )
            self.storage.finalize_generation(
                root, project, entry_id,
                body=gen.body, display_name=gen.name, description=gen.description,
            )
            self._publish(project, entry_id, collection, "generate", "completed")
        except Exception as e:  # noqa: BLE001 - surface to UI, don't crash the loop
            self.storage.fail_operation(root, project, collection, entry_id, str(e))
            self._publish(project, entry_id, collection, "generate", "failed", str(e))

    # ── chat ──────────────────────────────────────────────────────────────────────

    def start_chat(self, root: str, project: str, collection: str, entry_id: str,
                   *, message: str) -> None:
        self._spawn(self._run_chat(root, project, collection, entry_id, message=message))

    async def _run_chat(self, root: str, project: str, collection: str, entry_id: str,
                        *, message: str) -> None:
        try:
            entry, body, _ = self.storage.read_document(root, project, collection, entry_id)
            chat = self.storage.read_chat(root, project, collection, entry_id)
            turn = await self.claude.chat(
                root=root, project=project, doc_type=entry.type,
                body=body, message=message, session_id=chat.session_id,
            )
            if turn.session_id:
                self.storage.set_chat_session(root, project, collection, entry_id,
                                              turn.session_id)
            if turn.revised_body is not None:
                self.storage.save_body(root, project, collection, entry_id,
                                       turn.revised_body)
            self.storage.append_chat_message(
                root, project, collection, entry_id, "assistant", turn.reply,
                revised_body=turn.revised_body is not None,
            )
            self.storage.clear_operation(root, project, collection, entry_id)
            self._publish(project, entry_id, collection, "chat", "completed")
        except Exception as e:  # noqa: BLE001
            self.storage.fail_operation(root, project, collection, entry_id, str(e))
            self.storage.append_chat_message(
                root, project, collection, entry_id, "assistant",
                f"(chat failed: {e})",
            )
            self._publish(project, entry_id, collection, "chat", "failed", str(e))
