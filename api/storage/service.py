"""StorageService — the single storage surface the API depends on (01 §5).

Pure-ish: paths in, data out, no network. All metadata writes are atomic + locked
(via :mod:`.atomic`) so UI edits and MCP callbacks can't corrupt each other.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..models import (
    ChatHistory,
    ChatMessage,
    Comment,
    CommentAnchor,
    CommentKind,
    CommentsFile,
    DependencyGraph,
    DiffComment,
    DocType,
    MetadataEntry,
    Operation,
    PermissionsConfig,
    ProgressState,
    ProjectDescriptor,
    TaskStatus,
)
from . import comments as comment_io
from . import graph as graph_util
from . import paths, registry
from .atomic import read_json, write_json
from .slug import dedupe_slug, slugify


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class StorageError(Exception):
    """Domain error raised by StorageService. Carries an HTTP status + code so
    the API can render a consistent ``{error:{code,message}}`` envelope (02)."""

    def __init__(self, message: str, *, status: int = 400, code: str = "storage_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class NotFoundError(StorageError):
    def __init__(self, message: str):
        super().__init__(message, status=404, code="not_found")


class ConflictError(StorageError):
    def __init__(self, message: str):
        super().__init__(message, status=409, code="conflict")


class ValidationError(StorageError):
    def __init__(self, message: str):
        super().__init__(message, status=422, code="validation")


class StorageService:
    # ── Projects ──────────────────────────────────────────────────────────────

    def list_projects(self) -> list[ProjectDescriptor]:
        return registry.list_projects()

    def get_project(self, name: str) -> Optional[ProjectDescriptor]:
        return registry.get_project(name)

    def create_project(self, name: str, root: str) -> ProjectDescriptor:
        """Register a project and create its on-disk skeleton. The caller (02)
        is responsible for validating that ``root`` exists and is a git repo."""
        paths.ensure_skeleton(root, name)
        self.ensure_gitignore(root)
        return registry.upsert_project(name, root)

    def touch_project(self, name: str) -> None:
        registry.touch_project(name)

    def remove_project(self, name: str) -> None:
        registry.remove_project(name)

    def ensure_gitignore(self, root: str) -> None:
        """Idempotently ensure the root ``.gitignore`` ignores execution
        worktrees (07). Only appends the line if missing."""
        line = "projects/*/executions/*/worktree/"
        gi = Path(root) / ".gitignore"
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if line in existing.splitlines():
            return
        prefix = "" if existing.endswith("\n") or existing == "" else "\n"
        from .atomic import atomic_write_text

        atomic_write_text(
            gi,
            existing + prefix + "# Promptly execution worktrees\n" + line + "\n",
        )

    # ── Metadata collections ──────────────────────────────────────────────────

    def _collection_for(self, type_: DocType | str) -> str:
        t = type_.value if isinstance(type_, DocType) else type_
        return "tasks" if t == DocType.task.value else "docs"

    def _meta_path(self, root: str, name: str, collection: str) -> Path:
        return (
            paths.tasks_json_path(root, name)
            if collection == "tasks"
            else paths.docs_json_path(root, name)
        )

    def read_metadata(
        self, root: str, name: str, collection: str
    ) -> dict[str, MetadataEntry]:
        raw = read_json(self._meta_path(root, name, collection), default={}) or {}
        return {eid: MetadataEntry.model_validate(e) for eid, e in raw.items()}

    def _write_metadata(
        self, root: str, name: str, collection: str, entries: dict[str, MetadataEntry]
    ) -> None:
        write_json(
            self._meta_path(root, name, collection),
            {
                eid: e.model_dump(by_alias=True, exclude_none=True)
                for eid, e in entries.items()
            },
        )

    def get_entry(
        self, root: str, name: str, collection: str, entry_id: str
    ) -> MetadataEntry:
        entries = self.read_metadata(root, name, collection)
        if entry_id not in entries:
            raise NotFoundError(f"{collection[:-1]} {entry_id} not found")
        return entries[entry_id]

    def _file_for(self, collection: str, type_: str, slug: str) -> str:
        if type_ == DocType.project_spec.value:
            return "project.md"
        sub = "tasks" if collection == "tasks" else "docs"
        return f"{sub}/{slug}.md"

    def create_entry(
        self,
        root: str,
        name: str,
        *,
        type: DocType | str,
        display_name: str,
        body: str = "",
        description: str = "",
        depends_on: Optional[list[str]] = None,
        task_group: Optional[str] = None,
        custom: Optional[dict[str, Any]] = None,
    ) -> MetadataEntry:
        type_val = type.value if isinstance(type, DocType) else type
        collection = self._collection_for(type_val)
        entries = self.read_metadata(root, name, collection)

        if type_val == DocType.project_spec.value and any(
            e.type == DocType.project_spec.value for e in entries.values()
        ):
            raise ConflictError("a project_spec already exists")

        depends_on = depends_on or []
        if depends_on and (missing := [d for d in depends_on if d not in entries]):
            raise ValidationError(f"unknown dependsOn ids: {missing}")

        eid = _new_id()
        if graph_util.would_create_cycle(entries, eid, depends_on):
            raise ValidationError("dependsOn would create a cycle")

        if type_val == DocType.project_spec.value:
            file = "project.md"
        else:
            taken = {Path(e.file).stem for e in entries.values()}
            slug = dedupe_slug(slugify(display_name), taken)
            file = self._file_for(collection, type_val, slug)

        now = _now()
        entry = MetadataEntry(
            id=eid,
            name=display_name,
            type=type_val,
            description=description,
            status=TaskStatus.pending.value if type_val == DocType.task.value else None,
            task_group=task_group,
            depends_on=depends_on,
            custom=custom or {},
            file=file,
            created_at=now,
            updated_at=now,
        )
        # Write the body first, then commit metadata (so a half-write leaves no
        # dangling metadata entry pointing at a missing file).
        self._write_body_file(root, name, file, body, [])
        entries[eid] = entry
        self._write_metadata(root, name, collection, entries)
        return entry

    def patch_metadata(
        self, root: str, name: str, collection: str, entry_id: str, patch: dict[str, Any]
    ) -> MetadataEntry:
        entries = self.read_metadata(root, name, collection)
        if entry_id not in entries:
            raise NotFoundError(f"{collection[:-1]} {entry_id} not found")
        entry = entries[entry_id]

        if "depends_on" in patch or "dependsOn" in patch:
            new_deps = patch.get("depends_on", patch.get("dependsOn")) or []
            if missing := [d for d in new_deps if d not in entries and d != entry_id]:
                raise ValidationError(f"unknown dependsOn ids: {missing}")
            if graph_util.would_create_cycle(entries, entry_id, new_deps):
                raise ValidationError("dependsOn would create a cycle")

        data = entry.model_dump(by_alias=True)
        data.update(patch)
        data["updatedAt"] = _now()
        updated = MetadataEntry.model_validate(data)
        entries[entry_id] = updated
        self._write_metadata(root, name, collection, entries)
        return updated

    def set_status(
        self, root: str, name: str, task_id: str, status: TaskStatus | str
    ) -> MetadataEntry:
        return self.patch_metadata(
            root, name, "tasks", task_id,
            {"status": status.value if isinstance(status, TaskStatus) else status},
        )

    def remove_entry(self, root: str, name: str, collection: str, entry_id: str) -> MetadataEntry:
        """Soft-remove: set status=removed, keep the entry so references don't
        dangle (01 §2, §5)."""
        return self.patch_metadata(
            root, name, collection, entry_id, {"status": TaskStatus.removed.value}
        )

    # ── Document bodies + in-file comments ─────────────────────────────────────

    def _body_abs(self, root: str, name: str, file: str) -> Path:
        return paths.project_dir(root, name) / file

    def _write_body_file(
        self, root: str, name: str, file: str, body: str, comments: list[Comment]
    ) -> None:
        from .atomic import atomic_write_text

        atomic_write_text(
            self._body_abs(root, name, file),
            comment_io.serialize_document(body, comments),
        )

    def read_document(
        self, root: str, name: str, collection: str, entry_id: str
    ) -> tuple[MetadataEntry, str, list[Comment]]:
        entry = self.get_entry(root, name, collection, entry_id)
        path = self._body_abs(root, name, entry.file)
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        body, comments = comment_io.parse_document(raw)
        return entry, body, comments

    def save_body(
        self, root: str, name: str, collection: str, entry_id: str, body: str
    ) -> MetadataEntry:
        """Replace the body, preserving (and re-anchoring) existing comments."""
        entry, _, comments = self.read_document(root, name, collection, entry_id)
        comments = comment_io.reanchor(body, comments)
        self._write_body_file(root, name, entry.file, body, comments)
        return self.patch_metadata(root, name, collection, entry_id, {})

    def add_comment(
        self,
        root: str,
        name: str,
        collection: str,
        entry_id: str,
        *,
        anchor: CommentAnchor | dict,
        body: str,
        kind: CommentKind | str = CommentKind.comment,
        author: str = "user",
    ) -> Comment:
        entry, doc_body, existing = self.read_document(root, name, collection, entry_id)
        comment = Comment(
            id=_new_id(),
            anchor=CommentAnchor.model_validate(anchor) if isinstance(anchor, dict) else anchor,
            body=body,
            kind=kind.value if isinstance(kind, CommentKind) else kind,
            author=author,
            created_at=_now(),
        )
        existing.append(comment)
        self._write_body_file(root, name, entry.file, doc_body, existing)
        return comment

    def update_comment(
        self, root: str, name: str, collection: str, entry_id: str, comment_id: str,
        patch: dict[str, Any],
    ) -> Comment:
        entry, doc_body, existing = self.read_document(root, name, collection, entry_id)
        target = next((c for c in existing if c.id == comment_id), None)
        if target is None:
            raise NotFoundError(f"comment {comment_id} not found")
        data = target.model_dump(by_alias=True)
        data.update(patch)
        updated = Comment.model_validate(data)
        existing = [updated if c.id == comment_id else c for c in existing]
        self._write_body_file(root, name, entry.file, doc_body, existing)
        return updated

    # ── Graph ──────────────────────────────────────────────────────────────────

    def dependency_graph(
        self, root: str, name: str, include_removed: bool = False
    ) -> DependencyGraph:
        entries = self.read_metadata(root, name, "tasks")
        return graph_util.build_graph(entries, include_removed=include_removed)

    # ── Permissions config (09) ──────────────────────────────────────────────────

    def read_permissions(self, root: str, name: str) -> PermissionsConfig:
        raw = read_json(paths.permissions_path(root, name))
        return PermissionsConfig.model_validate(raw) if raw else PermissionsConfig()

    def write_permissions(
        self, root: str, name: str, config: PermissionsConfig
    ) -> PermissionsConfig:
        write_json(
            paths.permissions_path(root, name), config.model_dump(by_alias=True)
        )
        return config

    # ── Async operations (03/05) ──────────────────────────────────────────────────

    def create_placeholder(
        self,
        root: str,
        name: str,
        *,
        type: DocType | str,
        provisional_name: str,
        depends_on: Optional[list[str]] = None,
        task_group: Optional[str] = None,
        custom: Optional[dict[str, Any]] = None,
    ) -> MetadataEntry:
        """Create a metadata entry with an empty body and a running ``generate``
        operation, so it shows in the sidebar (with a spinner) immediately. The
        body/name/description fill in via :meth:`finalize_generation`."""
        entry = self.create_entry(
            root, name, type=type, display_name=provisional_name, body="",
            description="", depends_on=depends_on, task_group=task_group, custom=custom,
        )
        op = Operation(type="generate", status="running", started_at=_now())
        collection = self._collection_for(entry.type)
        return self.patch_metadata(
            root, name, collection, entry.id,
            {"operation": op.model_dump(by_alias=True)},
        )

    def finalize_generation(
        self, root: str, name: str, entry_id: str, *, body: str,
        display_name: Optional[str] = None, description: Optional[str] = None,
    ) -> MetadataEntry:
        """Write the generated body + metadata and clear the operation. Renames
        the file to match the final name (except the project spec)."""
        collection_guess = "docs"
        if entry_id not in self.read_metadata(root, name, "docs"):
            collection_guess = "tasks"
        entry = self.get_entry(root, name, collection_guess, entry_id)
        self._write_body_file(root, name, entry.file, body, [])

        patch: dict[str, Any] = {"operation": None}
        if description is not None:
            patch["description"] = description
        if display_name:
            patch["name"] = display_name
            if entry.type != DocType.project_spec.value:
                self._maybe_rename(root, name, collection_guess, entry, display_name, patch)
        return self.patch_metadata(root, name, collection_guess, entry_id, patch)

    def _maybe_rename(
        self, root: str, name: str, collection: str, entry: MetadataEntry,
        new_name: str, patch: dict[str, Any],
    ) -> None:
        sub = "tasks" if collection == "tasks" else "docs"
        new_slug = slugify(new_name)
        if Path(entry.file).stem == new_slug:
            return
        others = self.read_metadata(root, name, collection)
        taken = {Path(e.file).stem for eid, e in others.items() if eid != entry.id}
        new_slug = dedupe_slug(new_slug, taken)
        new_file = f"{sub}/{new_slug}.md"
        old_abs = self._body_abs(root, name, entry.file)
        new_abs = self._body_abs(root, name, new_file)
        if old_abs.exists():
            new_abs.parent.mkdir(parents=True, exist_ok=True)
            import os
            os.replace(old_abs, new_abs)
        patch["file"] = new_file

    def begin_operation(
        self, root: str, name: str, collection: str, entry_id: str, op_type: str
    ) -> MetadataEntry:
        op = Operation(type=op_type, status="running", started_at=_now())
        return self.patch_metadata(
            root, name, collection, entry_id,
            {"operation": op.model_dump(by_alias=True)},
        )

    def clear_operation(
        self, root: str, name: str, collection: str, entry_id: str
    ) -> MetadataEntry:
        return self.patch_metadata(root, name, collection, entry_id, {"operation": None})

    def fail_operation(
        self, root: str, name: str, collection: str, entry_id: str, error: str
    ) -> MetadataEntry:
        entry = self.get_entry(root, name, collection, entry_id)
        op = entry.operation or Operation(type="generate", started_at=_now())
        op.status = "failed"
        op.error = error
        return self.patch_metadata(
            root, name, collection, entry_id,
            {"operation": op.model_dump(by_alias=True)},
        )

    # ── Doc chat history (01/05) ──────────────────────────────────────────────────

    def read_chat(self, root: str, name: str, collection: str, entry_id: str) -> ChatHistory:
        raw = read_json(paths.chat_path(root, name, collection, entry_id))
        if raw:
            return ChatHistory.model_validate(raw)
        return ChatHistory(entry_id=entry_id)

    def _write_chat(self, root: str, name: str, collection: str, chat: ChatHistory) -> None:
        write_json(
            paths.chat_path(root, name, collection, chat.entry_id),
            chat.model_dump(by_alias=True),
        )

    def append_chat_message(
        self, root: str, name: str, collection: str, entry_id: str,
        role: str, content: str, revised_body: bool = False,
    ) -> ChatMessage:
        chat = self.read_chat(root, name, collection, entry_id)
        msg = ChatMessage(
            id=_new_id(), role=role, content=content,
            revised_body=revised_body, created_at=_now(),
        )
        chat.messages.append(msg)
        self._write_chat(root, name, collection, chat)
        return msg

    def set_chat_session(
        self, root: str, name: str, collection: str, entry_id: str, session_id: str
    ) -> None:
        chat = self.read_chat(root, name, collection, entry_id)
        chat.session_id = session_id
        self._write_chat(root, name, collection, chat)

    # ── Execution state ─────────────────────────────────────────────────────────

    def create_execution(
        self, root: str, name: str, execution_id: str, task_id: str
    ) -> ProgressState:
        now = _now()
        state = ProgressState(
            execution_id=execution_id,
            task_id=task_id,
            session_id=None,
            created_at=now,
            updated_at=now,
        )
        self.write_progress(root, name, state)
        write_json(paths.diff_comments_path(root, name, execution_id), {"byCommit": {}})
        return state

    def read_progress(
        self, root: str, name: str, execution_id: str
    ) -> Optional[ProgressState]:
        raw = read_json(paths.progress_path(root, name, execution_id))
        return ProgressState.model_validate(raw) if raw else None

    def write_progress(self, root: str, name: str, state: ProgressState) -> ProgressState:
        state.updated_at = _now()
        write_json(
            paths.progress_path(root, name, state.execution_id),
            state.model_dump(by_alias=True),
        )
        return state

    def read_diff_comments(self, root: str, name: str, execution_id: str) -> CommentsFile:
        raw = read_json(
            paths.diff_comments_path(root, name, execution_id), default={"byCommit": {}}
        )
        return CommentsFile.model_validate(raw)

    def add_diff_comment(
        self, root: str, name: str, execution_id: str, commit: str, comment: DiffComment
    ) -> DiffComment:
        cf = self.read_diff_comments(root, name, execution_id)
        cf.by_commit.setdefault(commit, []).append(comment)
        write_json(
            paths.diff_comments_path(root, name, execution_id),
            cf.model_dump(by_alias=True),
        )
        return comment
