"""Pytest fixtures and configuration."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_from_outer_git(monkeypatch):
    """Strip GIT_* (GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE, ...) from the environment of every test.

    git exports these to hooks, notably when committing from a linked worktree, and the pre-commit hook runs this
    suite. Tests that build throwaway repos under tmp_path (and the code they exercise, which shells out to git)
    would otherwise act on the repository being committed and overwrite its staging area.
    """
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A temporary directory used as project root (e.g. for git/template paths)."""
    return tmp_path


@pytest.fixture
def template_content() -> str:
    """Minimal template with {{VERSION}} placeholder."""
    return "# Release v{{VERSION}}\n\n## Changes\n- List items\n"
