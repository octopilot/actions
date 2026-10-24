"""Unit tests for the release action entrypoint (main.py)."""

import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Load actions/release/main.py as a module (requires PYTHONPATH=common so "from common.notes" resolves).
_actions_release = Path(__file__).resolve().parents[3] / "release"
spec = importlib.util.spec_from_file_location("release_main", _actions_release / "main.py")
assert spec and spec.loader
release_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_main)


def test_main_exits_1_when_version_missing(tmp_path: Path) -> None:
    """When INPUT_VERSION is missing, main exits 1."""
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "INPUT_VERSION": "",
    }
    with patch.dict(os.environ, env, clear=False), pytest.raises(SystemExit) as exc_info:
        release_main.main()
    assert exc_info.value.code == 1


def test_main_exits_1_when_workspace_missing() -> None:
    """When GITHUB_WORKSPACE is missing, main exits 1."""
    with patch.dict(os.environ, {"GITHUB_WORKSPACE": ""}, clear=False), pytest.raises(SystemExit) as exc_info:
        release_main.main()
    assert exc_info.value.code == 1


def test_main_sets_github_output_on_success(tmp_path: Path) -> None:
    """When notes.run succeeds, main writes body_file and body to GITHUB_OUTPUT."""
    output_file = tmp_path / "out"
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "INPUT_VERSION": "1.0.0",
        "INPUT_PROVIDER": "anthropic",
        "INPUT_OUTPUT_FILENAME": "release-body.md",
        "GITHUB_OUTPUT": str(output_file),
    }
    with patch.dict(os.environ, env, clear=False):
        with patch.object(release_main, "run_notes", return_value="# Release 1.0.0\n\nDone."):
            try:
                release_main.main()
            except SystemExit as e:
                assert e.code == 0, f"expected exit 0, got {e.code}"
    assert output_file.exists()
    content = output_file.read_text()
    assert "body_file=release-body.md" in content
    assert "Release 1.0.0" in content


def test_main_falls_back_to_the_commit_list_on_release_notes_error(tmp_path: Path) -> None:
    """A provider failure (down, unreachable, out of credit) warns and writes plain notes; the release goes ahead."""
    from common.notes import ReleaseNotesError

    output_file = tmp_path / "out"
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(output_file),
        "INPUT_VERSION": "1.0.0",
        "INPUT_PROVIDER": "anthropic",
    }
    with patch.dict(os.environ, env, clear=False):
        with patch.object(release_main, "run_notes", side_effect=ReleaseNotesError("credit balance is too low")):
            with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
                with patch("common.notes.get_commits_since", return_value=["fix: x", "feat: y"]):
                    with pytest.raises(SystemExit) as exc_info:
                        release_main.main()
    assert exc_info.value.code == 0
    notes = (tmp_path / "release_notes.md").read_text()
    assert notes.startswith("# Release 1.0.0")
    assert "- fix: x" in notes and "- feat: y" in notes
    assert "body_file=release_notes.md" in output_file.read_text()
