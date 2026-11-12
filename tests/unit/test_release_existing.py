"""The release job leaves an already-published GitHub Release alone (library-release.yml publishes it before the tag
run gets there, and published releases take no new assets); it creates one when none exists and fills a draft."""

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".github" / "workflows" / "pipeline.yml"

FAKE_CURL = r"""#!/usr/bin/env bash
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift ;; esac
  shift
done
[ -n "${FAKE_BODY:-}" ] && printf '%s' "$FAKE_BODY" > "$out"
printf '%s' "$FAKE_CODE"
"""


def steps() -> list[dict]:
    return yaml.safe_load(PIPELINE.read_text())["jobs"]["release"]["steps"]


def run(
    tmp_path: Path, code: str, body: str = "", assets: bool = False
) -> tuple[subprocess.CompletedProcess, str, str]:
    work, bin_dir = tmp_path / "work", tmp_path / "bin"
    work.mkdir()
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    if assets:
        (work / "release_result.json").write_text("{}")
        (work / "dist").mkdir()
        (work / "dist" / "tool.tar.gz").write_text("x")
    out, summary = tmp_path / "out", tmp_path / "summary.md"
    out.touch()
    step = next(s for s in steps() if s.get("id") == "existing")
    proc = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=work,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_CODE": code,
            "FAKE_BODY": body,
            "GH_TOKEN": "t",
            "GITHUB_REPOSITORY": "acme/lib",
            "GITHUB_REF_NAME": "v0.1.1",
            "GITHUB_OUTPUT": str(out),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    assert not (work / "existing-release.json").exists()
    return proc, out.read_text(), summary.read_text() if summary.exists() else ""


def test_create_step_is_skipped_for_a_published_release():
    create = next(s for s in steps() if s.get("name") == "Create GitHub Release")
    assert create["if"] == "steps.existing.outputs.published != 'true'"


def test_published_release_is_left_alone(tmp_path):
    proc, out, summary = run(tmp_path, "200", '{"draft": false}', assets=True)
    assert proc.returncode == 0, proc.stderr
    assert "published=true" in out
    assert "already published" in summary
    assert "release_result.json" in summary and "dist/tool.tar.gz" in summary


def test_draft_release_is_filled(tmp_path):
    proc, out, _ = run(tmp_path, "200", '{"draft": true}')
    assert proc.returncode == 0, proc.stderr
    assert "published=false" in out


def test_missing_release_is_created(tmp_path):
    proc, out, summary = run(tmp_path, "404", '{"message": "Not Found"}')
    assert proc.returncode == 0, proc.stderr
    assert "published=false" in out
    assert summary == ""


def test_lookup_error_fails_the_job(tmp_path):
    proc, out, _ = run(tmp_path, "500", "{}")
    assert proc.returncode == 1
    assert "HTTP 500" in proc.stdout
    assert out == ""
