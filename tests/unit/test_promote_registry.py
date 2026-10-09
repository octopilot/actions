"""promote-registry copies build_result.json artifacts registry to registry by digest: images take the version tag,
charts keep theirs, order is kept, re-runs resume, and a moved tag, a foreign or undigested ref, or a failed copy
fails the promotion."""

import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "promote-registry" / "promote.sh"
PIPELINE = ROOT / ".github" / "workflows" / "pipeline.yml"
SRC = "us-docker.pkg.dev/proj/integration"
DST = "us-docker.pkg.dev/proj/pp"

FAKE_CRANE = r"""#!/usr/bin/env bash
key() { echo "$1" | tr '/:@' '___'; }
echo "$*" >> "$STATE/calls"
case "$1" in
  cp)
    [ -n "${FAIL_ON:-}" ] && echo "$2" | grep -q "$FAIL_ON" && { echo "copy failed" >&2; exit 1; }
    echo "${WRONG_DIGEST:-${2##*@}}" > "$STATE/$(key "$3")" ;;
  digest)
    f="$STATE/$(key "$2")"; [ -f "$f" ] && cat "$f" || exit 1 ;;
esac
"""


def key(ref: str) -> str:
    return ref.replace("/", "_").replace(":", "_").replace("@", "_")


def run(tmp_path: Path, builds: list[dict], **env: str) -> tuple[subprocess.CompletedProcess, Path]:
    work, bin_dir, state = tmp_path / "work", tmp_path / "bin", tmp_path / "state"
    for d in (work, bin_dir, state):
        d.mkdir(exist_ok=True)
    crane = bin_dir / "crane"
    crane.write_text(FAKE_CRANE)
    crane.chmod(0o755)
    (work / "build_result.json").write_text(json.dumps({"builds": builds}))
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=work,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(state),
            "BUILD_RESULT": "build_result.json",
            "SRC_REGISTRY": SRC,
            "DST_REGISTRY": DST,
            "VERSION": "v1.0.0",
            "OUTPUT": "out.json",
            **env,
        },
        capture_output=True,
        text=True,
    )
    return proc, work


def image(i: int) -> dict:
    return {"imageName": f"ghcr.io/acme/svc-{i:02d}", "tag": f"{SRC}/app/svc-{i:02d}:latest@sha256:{i:064x}"}


CHART = {
    "imageName": "ghcr.io/acme/app-chart",
    "tag": f"{SRC}/app/app-chart/app:0.2.1@sha256:{99:064x}",
}


def test_promotes_images_and_chart_in_order(tmp_path: Path) -> None:
    proc, work = run(tmp_path, [image(i) for i in range(10)] + [CHART])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads((work / "out.json").read_text())
    assert out["version"] == "v1.0.0"
    tags = [b["tag"] for b in out["builds"]]
    assert tags[:10] == [f"{DST}/app/svc-{i:02d}:v1.0.0@sha256:{i:064x}" for i in range(10)]
    assert tags[10] == f"{DST}/app/app-chart/app:0.2.1@sha256:{99:064x}"


def test_rerun_skips_targets_already_promoted(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, [image(1), image(2)])
    assert proc.returncode == 0, proc.stderr
    (tmp_path / "state" / "calls").unlink()
    proc, _ = run(tmp_path, [image(1), image(2)])
    assert proc.returncode == 0, proc.stderr
    assert not any(c.startswith("cp ") for c in (tmp_path / "state" / "calls").read_text().splitlines())


def test_existing_tag_at_other_digest_fails(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / key(f"{DST}/app/svc-01:v1.0.0")).write_text(f"sha256:{7:064x}\n")
    proc, _ = run(tmp_path, [image(1)])
    assert proc.returncode != 0
    assert "never move" in proc.stdout


def test_ref_outside_source_or_without_digest_fails(tmp_path: Path) -> None:
    for tag in (f"ttl.sh/x/svc:1h@sha256:{1:064x}", f"{SRC}/app/svc:latest"):
        proc, _ = run(tmp_path, [{"imageName": "ghcr.io/acme/svc", "tag": tag}])
        assert proc.returncode != 0, tag
        assert "not a digest-pinned ref" in proc.stdout


def test_failed_copy_fails(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, [image(i) for i in range(8)], FAIL_ON="svc-05")
    assert proc.returncode != 0


def test_digest_mismatch_after_copy_fails(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, [image(3)], WRONG_DIGEST=f"sha256:{8:064x}")
    assert proc.returncode != 0
    assert "expected" in proc.stdout


def test_empty_build_result_fails(tmp_path: Path) -> None:
    proc, _ = run(tmp_path, [])
    assert proc.returncode != 0


def acceptance_job() -> dict:
    return yaml.safe_load(PIPELINE.read_text())["jobs"]["acceptance-promote"]


def test_acceptance_job_is_opt_in_tag_only_and_serialised() -> None:
    job = acceptance_job()
    cond = " ".join(job["if"].split())
    assert "startsWith(github.ref, 'refs/tags/')" in cond
    assert "inputs.acceptance_environment != ''" in cond
    assert "needs.release.result == 'success'" in cond
    assert job["environment"]["name"] == "${{ inputs.acceptance_environment }}"
    assert job["concurrency"]["cancel-in-progress"] is False
    assert job["permissions"]["id-token"] == "write"


def test_acceptance_job_promotes_only_commits_on_the_default_branch() -> None:
    steps = acceptance_job()["steps"]
    names = [s.get("name", "") for s in steps]
    assert names.index("Tagged commit is on the default branch") < names.index("Promote to the acceptance registry")
    on_main = next(s for s in steps if s.get("name") == "Tagged commit is on the default branch")["run"]
    assert "merge-base --is-ancestor" in on_main


def test_ghcr_release_is_optional() -> None:
    wf = yaml.safe_load(PIPELINE.read_text())
    assert wf[True]["workflow_call"]["inputs"]["release_to_ghcr"]["default"] is True
    steps = wf["jobs"]["release"]["steps"]
    for name in ("Login to GHCR", "Promote tested artifacts to GHCR (digest-pinned)"):
        step = next(s for s in steps if s.get("name") == name)
        assert "inputs.release_to_ghcr" in step["if"], name
