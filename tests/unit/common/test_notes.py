"""Unit tests for common.common.notes."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.notes import (
    DEFAULT_TEMPLATE,
    ReleaseNotesError,
    get_commits_since,
    get_previous_tag,
    load_template,
    run,
)


class TestGetPreviousTag:
    """Tests for get_previous_tag."""

    def test_returns_tag_when_found(self, repo_root: Path) -> None:
        with patch("common.notes.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(stdout="v1.0.0\n", stderr="", returncode=0)
            result = get_previous_tag(repo_root)
        assert result == "v1.0.0"

    def test_returns_none_when_no_tag(self, repo_root: Path) -> None:
        with patch("common.notes.subprocess.run") as run_mock:
            run_mock.side_effect = subprocess.CalledProcessError(128, "git", stderr="No names found")
            result = get_previous_tag(repo_root)
        assert result is None

    def test_strips_whitespace(self, repo_root: Path) -> None:
        with patch("common.notes.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(stdout="  v2.0.0  \n", stderr="", returncode=0)
            result = get_previous_tag(repo_root)
        assert result == "v2.0.0"


class TestGetCommitsSince:
    """Tests for get_commits_since."""

    def test_returns_commit_subjects(self, repo_root: Path) -> None:
        with patch("common.notes.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(
                stdout="feat: add x\nfix: y\n",
                stderr="",
                returncode=0,
            )
            result = get_commits_since(repo_root, "v1.0.0")
        assert result == ["feat: add x", "fix: y"]

    def test_returns_empty_list_when_no_commits(self, repo_root: Path) -> None:
        with patch("common.notes.subprocess.run") as run_mock:
            run_mock.return_value = MagicMock(stdout="\n", stderr="", returncode=0)
            result = get_commits_since(repo_root, "v1.0.0")
        assert result == []

    def test_raises_on_invalid_ref(self, repo_root: Path) -> None:
        with patch("common.notes.subprocess.run") as run_mock:
            run_mock.side_effect = subprocess.CalledProcessError(128, "git", stderr="fatal: bad ref")
            with pytest.raises(ReleaseNotesError) as exc_info:
                get_commits_since(repo_root, "badref")
        assert "badref" in str(exc_info.value) or "Invalid" in str(exc_info.value)


class TestLoadTemplate:
    """Tests for load_template."""

    def test_returns_default_when_path_none(self) -> None:
        result = load_template(None)
        assert "{{VERSION}}" in result
        assert "Release" in result

    def test_returns_default_when_path_missing(self, repo_root: Path) -> None:
        result = load_template(repo_root / "nonexistent.md")
        assert result == DEFAULT_TEMPLATE

    def test_returns_file_content_when_exists(self, repo_root: Path, template_content: str) -> None:
        path = repo_root / "custom.md"
        path.write_text(template_content)
        result = load_template(path)
        assert result == template_content
        assert "{{VERSION}}" in result


class TestRun:
    """Tests for run() - release notes generation."""

    def test_raises_when_no_previous_tag_and_no_since_tag(self, repo_root: Path) -> None:
        with patch("common.notes.get_previous_tag", return_value=None):
            with pytest.raises(ReleaseNotesError) as exc_info:
                run(repo_root, "1.0.0")
        assert "previous tag" in str(exc_info.value).lower()

    def test_raises_on_invalid_provider(self, repo_root: Path) -> None:
        with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
            with patch("common.notes.get_commits_since", return_value=["fix: x"]):
                with pytest.raises(ReleaseNotesError) as exc_info:
                    run(repo_root, "1.0.0", provider="invalid")
        assert "provider" in str(exc_info.value).lower()

    def test_uses_since_tag_when_provided(self, repo_root: Path) -> None:
        with patch("common.notes.get_previous_tag", return_value=None):
            with patch("common.notes.get_commits_since", return_value=["feat: add"]) as get_commits:
                with patch("common.notes._call_anthropic", return_value="# Release\n\nDone."):
                    result = run(
                        repo_root,
                        "1.0.0",
                        since_tag="main",
                        provider="anthropic",
                    )
        assert result == "# Release\n\nDone."
        get_commits.assert_called_once_with(repo_root, "main")

    def test_writes_to_output_path(self, repo_root: Path) -> None:
        out = repo_root / "out" / "notes.md"
        with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
            with patch("common.notes.get_commits_since", return_value=["fix: bug"]):
                with patch("common.notes._call_openai", return_value="# v1.0.0\n\nFixed."):
                    result = run(
                        repo_root,
                        "1.0.0",
                        provider="openai",
                        output_path=out,
                    )
        assert result == "# v1.0.0\n\nFixed."
        assert out.read_text() == "# v1.0.0\n\nFixed."

    def test_returns_body_without_writing_when_no_output_path(self, repo_root: Path) -> None:
        with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
            with patch("common.notes.get_commits_since", return_value=["chore: bump"]):
                with patch("common.notes._call_anthropic", return_value="## Summary\nDone."):
                    result = run(repo_root, "1.0.0", provider="anthropic")
        assert result == "## Summary\nDone."

    def test_raises_when_openai_key_missing(self, repo_root: Path) -> None:
        with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
            with patch("common.notes.get_commits_since", return_value=["fix: x"]):
                with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                    with pytest.raises(ReleaseNotesError) as exc_info:
                        run(repo_root, "1.0.0", provider="openai")
        assert "OPENAI_API_KEY" in str(exc_info.value)

    def test_raises_when_anthropic_key_missing(self, repo_root: Path) -> None:
        with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
            with patch("common.notes.get_commits_since", return_value=["fix: x"]):
                with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
                    with pytest.raises(ReleaseNotesError) as exc_info:
                        run(repo_root, "1.0.0", provider="anthropic")
        assert "ANTHROPIC_API_KEY" in str(exc_info.value)

    def test_uses_custom_template_path(self, repo_root: Path, template_content: str) -> None:
        template_path = repo_root / "custom.md"
        template_path.write_text(template_content)
        with patch("common.notes.get_previous_tag", return_value="v0.9.0"):
            with patch("common.notes.get_commits_since", return_value=["feat: x"]):
                with patch("common.notes._call_anthropic") as call_mock:
                    call_mock.return_value = "Body"
                    run(
                        repo_root,
                        "2.0.0",
                        provider="anthropic",
                        template_path=template_path,
                    )
        # Format instructions passed to API should contain the custom template with version
        call_args = call_mock.call_args
        format_instructions = call_args[0][1]
        assert "2.0.0" in format_instructions
        assert "Release v2.0.0" in format_instructions or "v2.0.0" in format_instructions
