"""Pytest fixtures and configuration."""

from pathlib import Path

import pytest


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A temporary directory used as project root (e.g. for git/template paths)."""
    return tmp_path


@pytest.fixture
def template_content() -> str:
    """Minimal template with {{VERSION}} placeholder."""
    return "# Release v{{VERSION}}\n\n## Changes\n- List items\n"
