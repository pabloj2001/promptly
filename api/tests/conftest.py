import os
import subprocess
from pathlib import Path

import pytest

from api.storage import StorageService


@pytest.fixture
def promptly_home(tmp_path, monkeypatch):
    home = tmp_path / "promptly_home"
    home.mkdir()
    monkeypatch.setenv("PROMPTLY_HOME", str(home))
    return home


@pytest.fixture
def root(tmp_path):
    """A real git repo to act as the user's codebase root."""
    r = tmp_path / "codebase"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return str(r)


@pytest.fixture
def storage():
    return StorageService()


@pytest.fixture
def project(storage, root, promptly_home):
    storage.create_project("Demo Project", root)
    return ("Demo Project", root)
