import pytest
from fastapi.testclient import TestClient

from api.deps import get_claude, get_operations, get_storage
from api.main import create_app
from api.services.claude import GeneratedDoc


class FakeClaude:
    """Used for the synchronous `/address` + `plan_tasks` paths (called directly)."""

    async def address_comments(self, *, root, project, body, comments):
        return body + "\n\n<!-- addressed -->"

    async def plan_tasks(self, *, root, project):
        from api.services.claude import TaskStub
        return [
            TaskStub(name="Set up DB", description="schema", task_group="Backend"),
            TaskStub(name="Auth", description="login", task_group="Backend",
                     depends_on=["Set up DB"]),
        ]


class FakeOperations:
    """Runs 'background' work synchronously so tests are deterministic (no real CLI,
    no event-loop timing). Mirrors OperationManager's interface."""

    def __init__(self, storage):
        self.storage = storage

    def start_generation(self, root, project, entry_id, collection, *, prompt, type,
                         depends_on, name_hint):
        tval = type.value if hasattr(type, "value") else type
        self.storage.finalize_generation(
            root, project, entry_id,
            body=f"# {prompt}\n\nGenerated body for: {prompt}",
            display_name=name_hint or f"Generated {tval}",
            description="auto description",
        )

    def start_chat(self, root, project, collection, entry_id, *, message):
        self.storage.append_chat_message(
            root, project, collection, entry_id, "assistant", f"ack: {message}",
        )
        self.storage.clear_operation(root, project, collection, entry_id)


@pytest.fixture
def client(promptly_home, root):
    app = create_app()
    app.dependency_overrides[get_claude] = lambda: FakeClaude()
    app.dependency_overrides[get_operations] = lambda: FakeOperations(get_storage())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def proj(client, root):
    r = client.post("/projects", json={"name": "Demo", "root": root})
    assert r.status_code == 201, r.text
    return "Demo"


def q(project):
    return {"project": project}


# ── projects ────────────────────────────────────────────────────────────────────


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_project_validates_git_repo(client, tmp_path):
    nogit = tmp_path / "plain"
    nogit.mkdir()
    r = client.post("/projects", json={"name": "X", "root": str(nogit)})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation"


def test_create_and_list_projects(client, proj):
    r = client.get("/projects")
    assert r.status_code == 200
    assert any(p["name"] == "Demo" for p in r.json())


def test_duplicate_project_conflict(client, proj, root):
    r = client.post("/projects", json={"name": "Demo", "root": root})
    assert r.status_code == 409


def test_unknown_active_project_404(client):
    r = client.get("/docs", params={"project": "ghost"})
    assert r.status_code == 404


# ── docs ──────────────────────────────────────────────────────────────────────


def test_create_doc_via_prompt(client, proj):
    r = client.post("/docs", params=q(proj),
                    json={"prompt": "write API notes", "type": "doc", "name": "Notes"})
    assert r.status_code == 202, r.text  # async: placeholder returned
    entry = r.json()
    assert entry["file"] == "docs/notes.md"

    # FakeOperations finalized synchronously, so the body is already filled in.
    got = client.get(f"/docs/{entry['id']}", params=q(proj)).json()
    assert "Generated body" in got["body"]
    assert got["meta"]["operation"] is None
    assert got["comments"] == []


def test_doc_chat(client, proj):
    e = client.post("/docs", params=q(proj),
                    json={"prompt": "p", "type": "doc", "name": "D"}).json()
    r = client.post(f"/docs/{e['id']}/chat", params=q(proj), json={"message": "tighten it"})
    assert r.status_code == 202
    assert r.json()["role"] == "user"
    hist = client.get(f"/docs/{e['id']}/chat", params=q(proj)).json()
    roles = [m["role"] for m in hist["messages"]]
    assert roles == ["user", "assistant"]
    assert "ack: tighten it" in hist["messages"][1]["content"]


def test_import_doc_verbatim(client, proj):
    r = client.post("/docs/import", params=q(proj),
                    json={"name": "Imported", "type": "doc", "body": "# Hi\nverbatim"})
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["file"] == "docs/imported.md"
    got = client.get(f"/docs/{entry['id']}", params=q(proj)).json()
    assert got["body"].strip() == "# Hi\nverbatim"
    assert got["meta"]["operation"] is None  # no AI op


def test_import_project_spec(client, proj):
    r = client.post("/docs/import", params=q(proj),
                    json={"name": "Spec", "type": "project_spec", "body": "# Spec"})
    assert r.status_code == 201
    assert client.get(f"/projects/{proj}").json()["hasProjectSpec"] is True


def test_generate_tasks_from_spec(client, proj):
    # needs a project spec first
    r0 = client.post("/tasks/generate-from-spec", params=q(proj))
    assert r0.status_code == 422  # no spec yet

    client.post("/docs/import", params=q(proj),
                json={"name": "Spec", "type": "project_spec", "body": "# Spec"})
    r = client.post("/tasks/generate-from-spec", params=q(proj))
    assert r.status_code == 202, r.text
    placeholders = r.json()
    assert {p["name"] for p in placeholders} == {"Set up DB", "Auth"}

    tasks = client.get("/tasks", params=q(proj)).json()
    by_name = {t["name"]: t for t in tasks}
    # FakeOperations finalized bodies synchronously
    assert by_name["Auth"]["operation"] is None
    # dependency resolved by name -> id
    db_id = by_name["Set up DB"]["id"]
    assert by_name["Auth"]["dependsOn"] == [db_id]


def test_permissions_config_defaults_and_update(client, proj):
    cfg = client.get("/permissions", params=q(proj)).json()
    assert "Write" in cfg["generation"]["deny"]
    cfg["additionalReadDirs"] = ["/extra"]
    r = client.put("/permissions", params=q(proj), json=cfg)
    assert r.status_code == 200
    assert client.get("/permissions", params=q(proj)).json()["additionalReadDirs"] == ["/extra"]


def test_create_project_spec_and_flag(client, proj):
    client.post("/docs", params=q(proj),
                json={"prompt": "the spec", "type": "project_spec", "name": "Spec"})
    desc = client.get(f"/projects/{proj}").json()
    assert desc["hasProjectSpec"] is True


def test_edit_doc_body(client, proj):
    e = client.post("/docs", params=q(proj),
                    json={"prompt": "p", "type": "doc", "name": "D"}).json()
    r = client.put(f"/docs/{e['id']}", params=q(proj), json={"body": "manually edited"})
    assert r.status_code == 200
    got = client.get(f"/docs/{e['id']}", params=q(proj)).json()
    assert got["body"].strip() == "manually edited"


def test_comments_lifecycle(client, proj):
    e = client.post("/docs", params=q(proj),
                    json={"prompt": "hello world", "type": "doc", "name": "D"}).json()
    body = client.get(f"/docs/{e['id']}", params=q(proj)).json()["body"]
    idx = body.find("Generated")
    c = client.post(f"/docs/{e['id']}/comments", params=q(proj), json={
        "anchor": {"quote": "Generated", "start": idx, "end": idx + len("Generated")},
        "body": "why?", "kind": "question",
    })
    assert c.status_code == 201
    cid = c.json()["id"]
    upd = client.put(f"/docs/{e['id']}/comments/{cid}", params=q(proj),
                     json={"resolved": True})
    assert upd.json()["resolved"] is True


def test_address_comments_preview(client, proj):
    e = client.post("/docs", params=q(proj),
                    json={"prompt": "x", "type": "doc", "name": "D"}).json()
    r = client.post(f"/docs/{e['id']}/address", params=q(proj))
    assert r.status_code == 200
    assert "addressed" in r.json()["revisedBody"]


def test_soft_delete_doc(client, proj):
    e = client.post("/docs", params=q(proj),
                    json={"prompt": "x", "type": "doc", "name": "D"}).json()
    r = client.delete(f"/docs/{e['id']}", params=q(proj))
    assert r.json()["status"] == "removed"


# ── tasks / graph ───────────────────────────────────────────────────────────────


def test_create_task_and_graph(client, proj):
    a = client.post("/tasks", params=q(proj),
                    json={"prompt": "task a", "name": "A"}).json()
    b = client.post("/tasks", params=q(proj),
                    json={"prompt": "task b", "name": "B", "dependsOn": [a["id"]]}).json()
    assert a["status"] == "pending"
    g = client.get("/tasks/graph", params=q(proj)).json()
    assert {n["id"] for n in g["nodes"]} == {a["id"], b["id"]}
    assert g["edges"] == [{"source": a["id"], "target": b["id"]}]


def test_status_change(client, proj):
    t = client.post("/tasks", params=q(proj),
                    json={"prompt": "t", "name": "T"}).json()
    r = client.put(f"/tasks/{t['id']}/status", params=q(proj),
                   json={"status": "in_progress"})
    assert r.json()["status"] == "in_progress"


def test_cycle_rejected_via_metadata(client, proj):
    a = client.post("/tasks", params=q(proj), json={"prompt": "a", "name": "A"}).json()
    b = client.post("/tasks", params=q(proj),
                    json={"prompt": "b", "name": "B", "dependsOn": [a["id"]]}).json()
    r = client.put(f"/tasks/{a['id']}/metadata", params=q(proj),
                   json={"dependsOn": [b["id"]]})
    assert r.status_code == 422


def test_task_address_preview(client, proj):
    t = client.post("/tasks", params=q(proj), json={"prompt": "t", "name": "T"}).json()
    r = client.post(f"/tasks/{t['id']}/address", params=q(proj))
    assert r.status_code == 200
    assert "addressed" in r.json()["revisedBody"]


def test_metadata_custom_patch(client, proj):
    t = client.post("/tasks", params=q(proj), json={"prompt": "t", "name": "T"}).json()
    r = client.put(f"/tasks/{t['id']}/metadata", params=q(proj),
                   json={"custom": {"jira": "PROJ-1"}})
    assert r.json()["custom"]["jira"] == "PROJ-1"


# ── executions (02 surface) ──────────────────────────────────────────────────────


def test_diff_comments_storage(client, proj, storage, root):
    # progress.json must exist for read; create one directly via storage.
    storage.create_execution(root, "Demo", "exec-9", "task-9")
    r = client.post("/executions/exec-9/comments", params=q(proj), json={
        "commit": "sha1", "file": "a.py", "lineStart": 1, "lineEnd": 2, "body": "fix",
    })
    assert r.status_code == 201
    got = client.get("/executions/exec-9/comments", params=q(proj)).json()
    assert got["byCommit"]["sha1"][0]["file"] == "a.py"

    # resolve it
    cid = got["byCommit"]["sha1"][0]["id"]
    upd = client.put(f"/executions/exec-9/comments/{cid}", params=q(proj),
                     json={"resolved": True})
    assert upd.status_code == 200
    assert upd.json()["resolved"] is True


def test_get_progress_after_create(client, proj, storage, root):
    storage.create_execution(root, "Demo", "exec-10", "task-10")
    r = client.get("/executions/exec-10", params=q(proj))
    assert r.status_code == 200
    assert r.json()["status"] == "running"
