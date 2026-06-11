import pytest
from fastapi.testclient import TestClient

from api.deps import get_claude
from api.main import create_app
from api.services.claude import GeneratedDoc


class FakeClaude:
    async def generate_document(self, *, root, project, prompt, type, depends_on=None,
                                name_hint=None):
        return GeneratedDoc(
            name=name_hint or "Generated " + type.value if hasattr(type, "value") else "Generated",
            description="auto description",
            body=f"# {prompt}\n\nGenerated body for: {prompt}",
        )

    async def address_comments(self, *, root, project, body, comments):
        return body + "\n\n<!-- addressed -->"


@pytest.fixture
def client(promptly_home, root):
    app = create_app()
    app.dependency_overrides[get_claude] = lambda: FakeClaude()
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
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["file"] == "docs/notes.md"

    got = client.get(f"/docs/{entry['id']}", params=q(proj)).json()
    assert "Generated body" in got["body"]
    assert got["comments"] == []


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


def test_start_execution_not_implemented_yet(client, proj):
    t = client.post("/tasks", params=q(proj), json={"prompt": "t", "name": "T"}).json()
    r = client.post("/executions", params=q(proj), json={"taskId": t["id"]})
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"


def test_diff_comments_storage(client, proj, storage, root):
    # progress.json must exist for read; create one directly via storage.
    storage.create_execution(root, "Demo", "exec-9", "task-9")
    r = client.post("/executions/exec-9/comments", params=q(proj), json={
        "commit": "sha1", "file": "a.py", "lineStart": 1, "lineEnd": 2, "body": "fix",
    })
    assert r.status_code == 201
    got = client.get("/executions/exec-9/comments", params=q(proj)).json()
    assert got["byCommit"]["sha1"][0]["file"] == "a.py"


def test_get_progress_after_create(client, proj, storage, root):
    storage.create_execution(root, "Demo", "exec-10", "task-10")
    r = client.get("/executions/exec-10", params=q(proj))
    assert r.status_code == 200
    assert r.json()["status"] == "running"
