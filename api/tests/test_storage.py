from pathlib import Path

import pytest

from api.models import CommentAnchor, DocType, TaskStatus
from api.storage import StorageError, StorageService
from api.storage import comments as comment_io
from api.storage import graph as graph_util
from api.storage.slug import dedupe_slug, slugify


# ── slug ──────────────────────────────────────────────────────────────────────


def test_slugify_basic():
    assert slugify("Set up Auth!") == "set-up-auth"
    assert slugify("  Héllo  World  ") == "hello-world"
    assert slugify("") == "untitled"


def test_dedupe_slug():
    taken = {"auth", "auth-2"}
    assert dedupe_slug("auth", taken) == "auth-3"
    assert dedupe_slug("login", taken) == "login"


# ── registry / projects ────────────────────────────────────────────────────────


def test_create_and_list_project(storage, root, promptly_home):
    desc = storage.create_project("My App", root)
    assert desc.name == "My App"
    names = [p.name for p in storage.list_projects()]
    assert "My App" in names
    # skeleton dirs exist
    pdir = Path(root) / "projects" / "my-app"
    assert (pdir / "docs" / "docs.json").exists()
    assert (pdir / "tasks" / "tasks.json").exists()
    assert (pdir / "executions").is_dir()


def test_gitignore_idempotent(storage, root, promptly_home):
    storage.create_project("App", root)
    storage.ensure_gitignore(root)  # second call
    gi = (Path(root) / ".gitignore").read_text()
    assert gi.count("projects/*/executions/*/worktree/") == 1


def test_remove_project(storage, root, promptly_home):
    storage.create_project("Gone", root)
    storage.remove_project("Gone")
    assert storage.get_project("Gone") is None


# ── metadata CRUD ───────────────────────────────────────────────────────────────


def test_create_doc_writes_body_and_metadata(storage, project):
    name, root = project
    entry = storage.create_entry(
        root, name, type=DocType.doc, display_name="API Notes",
        body="# API\nstuff", description="notes",
    )
    assert entry.file == "docs/api-notes.md"
    assert entry.status is None
    _, body, comments = storage.read_document(root, name, "docs", entry.id)
    assert "stuff" in body
    assert comments == []


def test_create_task_defaults_pending(storage, project):
    name, root = project
    t = storage.create_entry(root, name, type=DocType.task, display_name="Set up auth")
    assert t.status == TaskStatus.pending.value
    assert t.file == "tasks/set-up-auth.md"


def test_project_spec_singleton(storage, project):
    name, root = project
    storage.create_entry(root, name, type=DocType.project_spec, display_name="Spec",
                         body="# Spec")
    with pytest.raises(StorageError):
        storage.create_entry(root, name, type=DocType.project_spec, display_name="Spec2")


def test_filename_dedupe(storage, project):
    name, root = project
    a = storage.create_entry(root, name, type=DocType.task, display_name="Auth")
    b = storage.create_entry(root, name, type=DocType.task, display_name="Auth")
    assert a.file != b.file
    assert {a.file, b.file} == {"tasks/auth.md", "tasks/auth-2.md"}


def test_patch_metadata_updates_timestamp(storage, project):
    name, root = project
    t = storage.create_entry(root, name, type=DocType.task, display_name="X")
    updated = storage.patch_metadata(root, name, "tasks", t.id,
                                     {"description": "new desc"})
    assert updated.description == "new desc"
    assert updated.updated_at >= t.updated_at


def test_set_status_and_soft_remove(storage, project):
    name, root = project
    t = storage.create_entry(root, name, type=DocType.task, display_name="X")
    storage.set_status(root, name, t.id, TaskStatus.in_progress)
    assert storage.get_entry(root, name, "tasks", t.id).status == "in_progress"
    storage.remove_entry(root, name, "tasks", t.id)
    assert storage.get_entry(root, name, "tasks", t.id).status == "removed"


def test_get_missing_entry_raises(storage, project):
    name, root = project
    with pytest.raises(StorageError):
        storage.get_entry(root, name, "tasks", "nope")


# ── dependencies / cycles ────────────────────────────────────────────────────────


def test_depends_on_unknown_rejected(storage, project):
    name, root = project
    with pytest.raises(StorageError):
        storage.create_entry(root, name, type=DocType.task, display_name="B",
                             depends_on=["ghost"])


def test_cycle_rejected_on_patch(storage, project):
    name, root = project
    a = storage.create_entry(root, name, type=DocType.task, display_name="A")
    b = storage.create_entry(root, name, type=DocType.task, display_name="B",
                             depends_on=[a.id])
    # a depends on b -> cycle a->b->a
    with pytest.raises(StorageError):
        storage.patch_metadata(root, name, "tasks", a.id, {"dependsOn": [b.id]})


def test_dependency_graph_excludes_removed(storage, project):
    name, root = project
    a = storage.create_entry(root, name, type=DocType.task, display_name="A")
    b = storage.create_entry(root, name, type=DocType.task, display_name="B",
                             depends_on=[a.id])
    storage.remove_entry(root, name, "tasks", a.id)
    g = storage.dependency_graph(root, name)
    ids = {n.id for n in g.nodes}
    assert a.id not in ids and b.id in ids
    assert g.edges == []  # edge to removed node dropped
    g_all = storage.dependency_graph(root, name, include_removed=True)
    assert a.id in {n.id for n in g_all.nodes}


# ── comment block parse/serialize/reanchor ───────────────────────────────────────


def test_comment_roundtrip(storage, project):
    name, root = project
    body = "The quick brown fox jumps."
    entry = storage.create_entry(root, name, type=DocType.doc, display_name="D",
                                 body=body)
    c = storage.add_comment(
        root, name, "docs", entry.id,
        anchor=CommentAnchor(quote="brown fox", start=10, end=19),
        body="why brown?", kind="question",
    )
    _, rbody, rcomments = storage.read_document(root, name, "docs", entry.id)
    assert rbody.rstrip() == body
    assert len(rcomments) == 1
    assert rcomments[0].id == c.id
    assert rcomments[0].kind == "question"


def test_clean_doc_has_no_comment_block(storage, project):
    name, root = project
    entry = storage.create_entry(root, name, type=DocType.doc, display_name="D",
                                 body="hello")
    raw = (Path(root) / "projects" / "demo-project" / entry.file).read_text()
    assert "promptly:comments" not in raw


def test_malformed_block_keeps_body():
    raw = "body text\n\n<!-- promptly:comments\n{not valid json}\n-->\n"
    body, comments = comment_io.parse_document(raw)
    assert body.startswith("body text")
    assert comments == []


def test_reanchor_finds_moved_quote():
    from api.models import Comment
    c = Comment(id="1", anchor=CommentAnchor(quote="fox", start=0, end=3),
                body="x", created_at="t")
    new_body = "the fox runs"
    [out] = comment_io.reanchor(new_body, [c])
    assert new_body[out.anchor.start:out.anchor.end] == "fox"
    assert out.orphaned is False


def test_reanchor_orphans_missing_quote():
    from api.models import Comment
    c = Comment(id="1", anchor=CommentAnchor(quote="zebra", start=0, end=5),
                body="x", created_at="t")
    [out] = comment_io.reanchor("no animals here", [c])
    assert out.orphaned is True


def test_save_body_reanchors(storage, project):
    name, root = project
    entry = storage.create_entry(root, name, type=DocType.doc, display_name="D",
                                 body="alpha beta gamma")
    storage.add_comment(root, name, "docs", entry.id,
                        anchor=CommentAnchor(quote="beta", start=6, end=10),
                        body="note")
    storage.save_body(root, name, "docs", entry.id, "prefix alpha beta gamma")
    _, _, comments = storage.read_document(root, name, "docs", entry.id)
    assert comments[0].orphaned is False
    assert comments[0].anchor.start == "prefix alpha ".__len__()


def test_update_comment_resolve(storage, project):
    name, root = project
    entry = storage.create_entry(root, name, type=DocType.doc, display_name="D",
                                 body="text here")
    c = storage.add_comment(root, name, "docs", entry.id,
                            anchor=CommentAnchor(quote="text", start=0, end=4),
                            body="q")
    storage.update_comment(root, name, "docs", entry.id, c.id, {"resolved": True})
    _, _, comments = storage.read_document(root, name, "docs", entry.id)
    assert comments[0].resolved is True


# ── execution state ──────────────────────────────────────────────────────────────


def test_execution_progress_roundtrip(storage, project):
    name, root = project
    state = storage.create_execution(root, name, "exec-1", "task-1")
    assert state.status == "running"
    read = storage.read_progress(root, name, "exec-1")
    assert read.task_id == "task-1"
    read.session_id = "sess-abc"
    storage.write_progress(root, name, read)
    assert storage.read_progress(root, name, "exec-1").session_id == "sess-abc"


def test_diff_comments_partitioned_by_commit(storage, project):
    from api.models import DiffComment
    name, root = project
    storage.create_execution(root, name, "exec-2", "task-2")
    dc = DiffComment(id="c1", file="src/x.py", line_start=1, line_end=2,
                     body="rename", created_at="t")
    storage.add_diff_comment(root, name, "exec-2", "sha123", dc)
    cf = storage.read_diff_comments(root, name, "exec-2")
    assert cf.by_commit["sha123"][0].file == "src/x.py"
