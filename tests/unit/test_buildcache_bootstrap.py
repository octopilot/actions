"""Build-cache image for pack: op v1.2.1+ creates a missing one itself (straight to the registry); older op keeps the
best-effort docker bootstrap, whose push goes through the runner's Docker daemon (and its pull-through proxy)."""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
STEPS = [
    (WORKFLOWS / "pipeline.yml", "integration-artifacts"),
    (WORKFLOWS / "integration-artifacts-wave.yml", "build"),
]


def cache_step(path: Path, job: str) -> dict:
    steps = yaml.safe_load(path.read_text())["jobs"][job]["steps"]
    return next(s for s in steps if s.get("name") == "Derive build-cache image name")


def run(tmp_path: Path, path: Path, job: str, op_version: str, docker_push_ok: bool) -> tuple[dict, list, str]:
    """Run the step with a fake docker that logs its calls; manifest inspect always misses (first run)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "docker-calls"
    calls.write_text("")
    push = "exit 0" if docker_push_ok else 'echo "error parsing HTTP 405 response body" >&2; exit 1'
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$1" >> "{calls}"\n'
        'case "$1" in\n'
        "  manifest) exit 1 ;;\n"
        "  import) cat >/dev/null; exit 0 ;;\n"
        f"  push) {push} ;;\n"
        "esac\n"
    )
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "out"
    out.write_text("")
    proc = subprocess.run(
        ["bash", "-c", cache_step(path, job)["run"]],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(out),
            "GITHUB_REPOSITORY_OWNER": "microscaler",
            "MATRIX_IMAGE": "pricewhisperer-suite:latest",
            "OP_VERSION": op_version,
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return outputs, calls.read_text().split(), proc.stdout + proc.stderr


@pytest.mark.parametrize(("path", "job"), STEPS)
@pytest.mark.parametrize("op_version", ["main", "latest", "v1.2.1", "v1.2.10", "v1.3.0", "v2.0.0"])
def test_op_creates_the_cache_no_daemon_push(tmp_path: Path, path: Path, job: str, op_version: str) -> None:
    outputs, calls, _ = run(tmp_path, path, job, op_version, docker_push_ok=False)
    assert outputs["image"] == "ghcr.io/microscaler/pricewhisperer-suite-buildcache"
    assert calls == [], "op creates the cache image; the step must not push through the daemon"


@pytest.mark.parametrize(("path", "job"), STEPS)
@pytest.mark.parametrize("op_version", ["v1.2.0", "v1.1.2", "v1.0.17"])
def test_older_op_keeps_the_docker_bootstrap(tmp_path: Path, path: Path, job: str, op_version: str) -> None:
    outputs, calls, _ = run(tmp_path, path, job, op_version, docker_push_ok=True)
    assert outputs["image"] == "ghcr.io/microscaler/pricewhisperer-suite-buildcache"
    assert calls == ["manifest", "import", "push"]


@pytest.mark.parametrize(("path", "job"), STEPS)
def test_older_op_builds_without_cache_when_the_push_is_refused(tmp_path: Path, path: Path, job: str) -> None:
    outputs, _, text = run(tmp_path, path, job, "v1.2.0", docker_push_ok=False)
    assert outputs["image"] == ""
    assert "::warning::build-cache bootstrap failed" in text
    assert "405" in text, "the warning says why"


@pytest.mark.parametrize(("path", "job"), STEPS)
def test_step_gets_the_op_version(path: Path, job: str) -> None:
    assert cache_step(path, job)["env"]["OP_VERSION"] == "${{ inputs.op_version }}"


def test_build_cache_can_be_turned_off() -> None:
    pipe = yaml.safe_load((WORKFLOWS / "pipeline.yml").read_text())
    assert pipe[True]["workflow_call"]["inputs"]["build_cache"]["default"] is True
    assert pipe["jobs"]["integration-artifacts-wave1"]["with"]["build_cache"] == "${{ inputs.build_cache }}"
    wave = yaml.safe_load((WORKFLOWS / "integration-artifacts-wave.yml").read_text())
    assert wave[True]["workflow_call"]["inputs"]["build_cache"]["default"] is True
    for path, job in STEPS:
        steps = yaml.safe_load(path.read_text())["jobs"][job]["steps"]
        for name in ("Login to GHCR for build cache", "Derive build-cache image name"):
            step = next(s for s in steps if s.get("name") == name)
            assert step["if"].startswith("inputs.build_cache && "), (path.name, name)
