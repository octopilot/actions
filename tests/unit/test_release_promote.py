"""The release job promotes build_result.json artifacts to ghcr.io in parallel, keeps their order, skips targets
already at the source digest (a re-run resumes) and fails when a copy fails."""

import json
import os
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".github" / "workflows" / "pipeline.yml"

FAKE_CRANE = r"""#!/usr/bin/env bash
# cp <src> <dst>: dst takes src's digest. digest <ref>: print it, or fail when the ref does not exist.
key() { echo "$1" | tr '/:@' '___'; }
echo "$*" >> "$STATE/calls"
case "$1" in
  cp)
    [ -n "${FAIL_ON:-}" ] && echo "$2" | grep -q "$FAIL_ON" && { echo "copy failed" >&2; exit 1; }
    sleep "${CRANE_SLEEP:-0}"
    echo "${2##*@}" > "$STATE/$(key "$3")" ;;
  digest)
    f="$STATE/$(key "$2")"; [ -f "$f" ] && cat "$f" || exit 1 ;;
esac
"""


def step_run() -> str:
    job = yaml.safe_load(PIPELINE.read_text())["jobs"]["release"]
    assert job["timeout-minutes"] >= 60
    return next(s for s in job["steps"] if s.get("name", "").startswith("Promote tested artifacts"))["run"]


def run(tmp_path: Path, builds: list[dict], **env: str) -> tuple[subprocess.CompletedProcess, Path]:
    work, bin_dir, state = tmp_path / "work", tmp_path / "bin", tmp_path / "state"
    for d in (work, bin_dir, state):
        d.mkdir(exist_ok=True)
    crane = bin_dir / "crane"
    crane.write_text(FAKE_CRANE)
    crane.chmod(0o755)
    (work / "build_result.json").write_text(json.dumps({"builds": builds}))
    chart = work / "helm" / "app"
    chart.mkdir(parents=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: app\nversion: 0.2.1\n")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True)
    proc = subprocess.run(
        ["bash", "-c", step_run()],
        cwd=work,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(state),
            "GITHUB_REF_NAME": "v1.0.0",
            "GITHUB_REPOSITORY_OWNER": "acme",
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
            **env,
        },
        capture_output=True,
        text=True,
    )
    return proc, work


def builds(n: int) -> list[dict]:
    return [
        {"imageName": f"ghcr.io/acme/svc-{i:02d}", "tag": f"reg.example/int/svc-{i:02d}:latest@sha256:{i:064x}"}
        for i in range(n)
    ]


def test_promotes_all_in_order(tmp_path: Path) -> None:
    proc, work = run(tmp_path, builds(12))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    released = json.loads((work / "release_result.json").read_text())["builds"]
    assert [b["imageName"] for b in released] == [f"ghcr.io/acme/svc-{i:02d}" for i in range(12)]
    assert released[3]["tag"] == f"ghcr.io/acme/svc-03:v1.0.0@sha256:{3:064x}"


def test_runs_copies_in_parallel(tmp_path: Path) -> None:
    # 12 copies of 0.5s each: about 6s one by one, about 1s six at a time.
    start = time.monotonic()
    proc, _ = run(tmp_path, builds(12), PROMOTE_PARALLEL="6", CRANE_SLEEP="0.5")
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = (tmp_path / "state" / "calls").read_text().splitlines()
    assert sum(c.startswith("cp ") for c in calls) == 12
    assert elapsed < 4, f"copies did not run in parallel ({elapsed:.1f}s)"


def test_skips_targets_already_promoted(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    # svc-01 was promoted by an earlier (cancelled) attempt.
    (state / "ghcr.io_acme_svc-01_v1.0.0").write_text(f"sha256:{1:064x}\n")
    proc, _ = run(tmp_path, builds(3))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "svc-01:v1.0.0 already at" in proc.stdout
    copies = [c for c in (state / "calls").read_text().splitlines() if c.startswith("cp ")]
    assert len(copies) == 2


def test_chart_source_gets_chart_name_segment(tmp_path: Path) -> None:
    chart = [{"imageName": "ghcr.io/acme/app-chart", "tag": f"reg.example/int/app-chart:0.2.1@sha256:{9:064x}"}]
    proc, _ = run(tmp_path, chart)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "promote: reg.example/int/app-chart/app:0.2.1@" in proc.stdout


def test_failed_copy_fails_the_step(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, builds(4), FAIL_ON="svc-02")
    assert proc.returncode != 0
