import pytest
from fastapi.testclient import TestClient

from api.deps import get_claude, get_execution, get_storage
from api.main import create_app


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

    async def derive_import_metadata(self, *, root, project, body, doc_type,
                                     current_name="", existing_tasks=None):
        # Infer a status only when the body clearly says so (mimics the prompt).
        status = "done" if "DONE" in body else ""
        return {
            "name": f"AI {current_name}",
            "description": "auto import description",
            "task_group": "Imported" if doc_type == "task" else "",
            "depends_on": [t["id"] for t in (existing_tasks or [])][:1],
            "status": status,
        }


_IMPORT_STATUSES = {"in_progress", "in_review", "blocked", "done"}


class FakeExecution:
    """Runs authoring executions synchronously so tests are deterministic (no real CLI,
    no event-loop timing). Mirrors ExecutionManager.start_authoring's observable effects:
    create/reuse the entry's authoring execution, apply the body/metadata, complete."""

    def __init__(self, storage, claude):
        self.storage = storage
        self.claude = claude

    async def start_authoring(self, root, project, collection, entry_id, *, mode,
                              message=""):
        entry = self.storage.get_entry(root, project, collection, entry_id)
        eid = entry.authoring_execution_id
        if not eid or self.storage.read_progress(root, project, eid) is None:
            eid = f"auth-{entry_id}"
            self.storage.create_execution(
                root, project, eid, entry_id, kind="doc", collection=collection)
            self.storage.patch_metadata(
                root, project, collection, entry_id, {"authoringExecutionId": eid})

        if mode == "generate":
            self.storage.save_body(
                root, project, collection, entry_id,
                f"# {message}\n\nGenerated body for: {message}")
            self.storage.patch_metadata(
                root, project, collection, entry_id, {"description": "auto description"})
        elif mode == "import":
            _, body, _ = self.storage.read_document(root, project, collection, entry_id)
            existing = None
            if collection == "tasks":
                existing = [{"id": t.id, "name": t.name, "description": t.description}
                            for t in self.storage.read_metadata(root, project, "tasks").values()
                            if t.id != entry_id and t.status != "removed"]
            meta = await self.claude.derive_import_metadata(
                root=root, project=project, body=body, doc_type=entry.type,
                current_name=entry.name, existing_tasks=existing)
            patch = {"description": meta.get("description", "")}
            if meta.get("name"):
                patch["name"] = meta["name"]
            if collection == "tasks":
                if meta.get("task_group"):
                    patch["taskGroup"] = meta["task_group"]
                known = {t["id"] for t in (existing or [])}
                deps = [d for d in meta.get("depends_on", []) if d in known]
                if deps:
                    patch["dependsOn"] = deps
                if meta.get("status") in _IMPORT_STATUSES:
                    patch["status"] = meta["status"]
            self.storage.patch_metadata(root, project, collection, entry_id, patch)
        elif mode == "chat":
            self.storage.append_chat_message(
                root, project, collection, entry_id, "assistant", f"ack: {message}")
        elif mode == "comment":
            _, body, _ = self.storage.read_document(root, project, collection, entry_id)
            self.storage.save_body(
                root, project, collection, entry_id, body + "\n\n<!-- addressed -->")

        self.storage.set_execution_status(root, project, eid, "completed")
        return self.storage.read_progress(root, project, eid)

    def pr_status(self, root, project, task):
        return {"hasPr": False, "merged": False, "state": "none"}


@pytest.fixture
def client(promptly_home, root):
    app = create_app()
    fake_claude = FakeClaude()
    app.dependency_overrides[get_claude] = lambda: fake_claude
    app.dependency_overrides[get_execution] = lambda: FakeExecution(
        get_storage(), fake_claude)
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
    assert got["meta"]["authoringExecutionId"]
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
    assert got["body"].strip() == "# Hi\nverbatim"  # body written verbatim
    # AI fills metadata via the authoring execution (synchronous in tests).
    assert got["meta"]["authoringExecutionId"]
    assert got["meta"]["description"] == "auto import description"


def test_import_task_fills_group(client, proj):
    r = client.post("/docs/import", params=q(proj),
                    json={"name": "Imported Task", "type": "task", "body": "# Do a thing"})
    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["file"].startswith("tasks/")
    got = client.get(f"/tasks/{entry['id']}", params=q(proj)).json()
    assert got["meta"]["description"] == "auto import description"
    assert got["meta"]["taskGroup"] == "Imported"


def test_import_infers_name_and_dependencies(client, proj):
    # First task: nothing to depend on, but still gets an AI-derived name.
    # (FakeOperations runs the metadata pass synchronously, so the rename is
    # already applied by the time we read it back.)
    first = client.post("/docs/import", params=q(proj),
                        json={"name": "First", "type": "task", "body": "# A"}).json()
    got_first = client.get(f"/tasks/{first['id']}", params=q(proj)).json()["meta"]
    assert got_first["name"] == "AI First"  # renamed by the metadata pass
    assert got_first["dependsOn"] == []  # no other tasks → no deps

    # Second task: should pick up a dependency on the existing one.
    second = client.post("/docs/import", params=q(proj),
                         json={"name": "Second", "type": "task", "body": "# B"}).json()
    got_second = client.get(f"/tasks/{second['id']}", params=q(proj)).json()["meta"]
    assert got_second["name"] == "AI Second"
    assert got_second["dependsOn"] == [first["id"]]
    # Status stays at the default unless the body clearly says otherwise.
    assert got_first["status"] == "pending"


def test_import_infers_status_when_stated(client, proj):
    done = client.post("/docs/import", params=q(proj),
                       json={"name": "Old", "type": "task",
                             "body": "# Already DONE\nshipped last week"}).json()
    meta = client.get(f"/tasks/{done['id']}", params=q(proj)).json()["meta"]
    assert meta["status"] == "done"

    pend = client.post("/docs/import", params=q(proj),
                       json={"name": "New", "type": "task", "body": "# todo"}).json()
    meta2 = client.get(f"/tasks/{pend['id']}", params=q(proj)).json()["meta"]
    assert meta2["status"] == "pending"


def test_import_doc_real_spawn(promptly_home, root):
    # Regression: import_doc must be `async def` so the authoring execution's background
    # spawn (asyncio.create_task) has a running loop. A sync endpoint runs in a threadpool
    # with no loop → 500 "Internal Server Error" → the client's JSON.parse blows up.
    from api.services.execution import ExecutionManager

    app = create_app()
    app.dependency_overrides[get_claude] = lambda: FakeClaude()
    app.dependency_overrides[get_execution] = lambda: ExecutionManager(
        get_storage(), claude=FakeClaude()
    )
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/projects", json={"name": "Demo", "root": root})
    r = c.post("/docs/import", params={"project": "Demo"},
               json={"name": "Imported", "type": "doc", "body": "# Hi"})
    assert r.status_code == 201, r.text


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
    # bodies authored synchronously via each task's authoring execution
    assert by_name["Auth"]["authoringExecutionId"]
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


def test_settings_defaults_and_update(client, proj):
    assert client.get("/settings", params=q(proj)).json() == {"instructions": ""}
    r = client.put("/settings", params=q(proj), json={"instructions": "run the build"})
    assert r.status_code == 200
    assert client.get("/settings", params=q(proj)).json()["instructions"] == "run the build"


def test_repos_registry_defaults_and_update(client, proj):
    # A primary repo is always present, even before anything is saved.
    repos = client.get("/repos", params=q(proj)).json()["repos"]
    assert len(repos) == 1 and repos[0]["primary"] and repos[0]["id"] == "primary"

    # Add an additional repo; primary is preserved and the new one gets an id.
    body = {"repos": repos + [{"id": "", "name": "lib", "url": "https://x/lib.git"}]}
    saved = client.put("/repos", params=q(proj), json=body).json()["repos"]
    assert len(saved) == 2 and saved[1]["name"] == "lib" and saved[1]["id"]
    assert sum(r["primary"] for r in saved) == 1

    # A non-primary repo without a url is rejected.
    bad = {"repos": [{"id": "", "name": "nopath", "url": ""}]}
    assert client.put("/repos", params=q(proj), json=bad).status_code == 422


def test_create_task_with_repo(client, proj):
    repos = client.get("/repos", params=q(proj)).json()["repos"]
    body = {"repos": repos + [{"id": "", "name": "lib", "url": "https://x/lib.git"}]}
    lib_id = client.put("/repos", params=q(proj), json=body).json()["repos"][1]["id"]
    t = client.post("/tasks", params=q(proj), json={"prompt": "do x", "repo": lib_id}).json()
    assert t["repo"] == lib_id


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


def test_address_comments_starts_execution(client, proj):
    e = client.post("/docs", params=q(proj),
                    json={"prompt": "x", "type": "doc", "name": "D"}).json()
    r = client.post(f"/docs/{e['id']}/address", params=q(proj))
    assert r.status_code == 200
    assert r.json()["status"] == "completed"  # authoring execution (comment mode)
    body = client.get(f"/docs/{e['id']}", params=q(proj)).json()["body"]
    assert "addressed" in body  # revision applied directly


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


def test_set_status_done_gated_on_pr(client, proj):
    t = client.post("/tasks", params=q(proj), json={"prompt": "t", "name": "T"}).json()
    # No PR -> marking done is gated (the client confirms + retries with force).
    r = client.put(f"/tasks/{t['id']}/status", params=q(proj), json={"status": "done"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "pr_not_merged"
    # force -> goes through.
    r2 = client.put(f"/tasks/{t['id']}/status", params=q(proj),
                    json={"status": "done", "force": True})
    assert r2.status_code == 200 and r2.json()["status"] == "done"
    # pr-status endpoint reports no PR.
    ps = client.get(f"/tasks/{t['id']}/pr-status", params=q(proj)).json()
    assert ps["hasPr"] is False


def test_cycle_rejected_via_metadata(client, proj):
    a = client.post("/tasks", params=q(proj), json={"prompt": "a", "name": "A"}).json()
    b = client.post("/tasks", params=q(proj),
                    json={"prompt": "b", "name": "B", "dependsOn": [a["id"]]}).json()
    r = client.put(f"/tasks/{a['id']}/metadata", params=q(proj),
                   json={"dependsOn": [b["id"]]})
    assert r.status_code == 422


def test_task_address_starts_execution(client, proj):
    t = client.post("/tasks", params=q(proj), json={"prompt": "t", "name": "T"}).json()
    r = client.post(f"/tasks/{t['id']}/address", params=q(proj))
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    body = client.get(f"/tasks/{t['id']}", params=q(proj)).json()["body"]
    assert "addressed" in body


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
