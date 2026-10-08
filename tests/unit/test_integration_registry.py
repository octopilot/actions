"""Integration artifacts can go to a private registry (integration_registry, logged in through Workload Identity
Federation) instead of ttl.sh; unset keeps ttl.sh."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
WIP = "projects/1/locations/global/workloadIdentityPools/github/providers/github"
SA = "github-actions@p.iam.gserviceaccount.com"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def where(tmp_path: Path, **env: str) -> tuple[int, dict, str]:
    """Run the integration-registry action's first step; returns (exit code, outputs, stdout+stderr)."""
    step = load(ROOT / "integration-registry" / "action.yml")["runs"]["steps"][0]
    out = tmp_path / "out"
    out.write_text("")
    base = {"REGISTRY": "", "AUTH": "", "WIP": "", "SA": "", "GITHUB_REPOSITORY": "microscaler/PriceWhisperer"}
    proc = subprocess.run(
        ["bash", "-c", step["run"]],
        env={"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out), **base, **env},
        capture_output=True,
        text=True,
    )
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return proc.returncode, outputs, proc.stdout + proc.stderr


def test_unset_means_ttl_sh(tmp_path: Path) -> None:
    code, outputs, _ = where(tmp_path)
    assert code == 0
    assert outputs["registry"] == ""


def test_private_registry_per_repository_lower_case(tmp_path: Path) -> None:
    code, outputs, _ = where(tmp_path, REGISTRY="us-docker.pkg.dev/pw-ctl/integration/", AUTH="gcp-wif", WIP=WIP, SA=SA)
    assert code == 0
    assert outputs["registry"] == "us-docker.pkg.dev/pw-ctl/integration/pricewhisperer"
    assert outputs["host"] == "us-docker.pkg.dev"


@pytest.mark.parametrize(
    "env",
    [
        {"REGISTRY": "r.example/x", "AUTH": "gcp-wif"},  # provider and service account missing
        {"REGISTRY": "r.example/x", "AUTH": "gcp-wif", "WIP": WIP},
        {"REGISTRY": "r.example/x", "AUTH": "aws-oidc"},
    ],
)
def test_bad_auth_fails(tmp_path: Path, env: dict) -> None:
    code, _, text = where(tmp_path, **env)
    assert code != 0
    assert "::error::" in text


def test_wif_login_writes_no_credentials_file() -> None:
    steps = load(ROOT / "integration-registry" / "action.yml")["runs"]["steps"]
    auth = next(s for s in steps if str(s.get("uses", "")).startswith("google-github-actions/auth@"))
    assert auth["with"]["create_credentials_file"] is False, "the checkout is the build context"
    assert auth["with"]["token_format"] == "access_token"


def registry_step(steps: list) -> dict:
    return next(s for s in steps if str(s.get("uses", "")).startswith("octopilot/actions/integration-registry@"))


@pytest.mark.parametrize(
    ("path", "job"),
    [
        (WORKFLOWS / "pipeline.yml", "integration-artifacts"),
        (WORKFLOWS / "integration-artifacts-wave.yml", "build"),
    ],
)
def test_integration_jobs_build_into_the_registry(path: Path, job: str) -> None:
    j = load(path)["jobs"][job]
    assert j["permissions"]["id-token"] == "write"
    names = [s.get("name", s.get("uses", "")) for s in j["steps"]]
    reg = registry_step(j["steps"])
    build = next(s for s in j["steps"] if s.get("name") == "Build and push artifact")
    assert names.index(reg["name"]) < names.index("Build and push artifact")
    assert build["with"]["registry"] == "${{ steps.ireg.outputs.registry }}"
    assert reg["with"]["registry"] == "${{ inputs.integration_registry }}"


def test_wave_one_gets_the_registry_inputs() -> None:
    call = load(WORKFLOWS / "pipeline.yml")["jobs"]["integration-artifacts-wave1"]
    assert call["permissions"]["id-token"] == "write"
    for name in ("integration_registry", "registry_auth", "gcp_workload_identity_provider", "gcp_service_account"):
        assert call["with"][name] == "${{ inputs." + name + " }}"
    wave_inputs = load(WORKFLOWS / "integration-artifacts-wave.yml")[True]["workflow_call"]["inputs"]
    assert all(wave_inputs[n].get("default") == "" for n in ("integration_registry", "registry_auth"))


def test_release_can_read_the_registry_before_promoting() -> None:
    rel = load(WORKFLOWS / "pipeline.yml")["jobs"]["release"]
    assert rel["permissions"]["id-token"] == "write"
    names = [s.get("name") for s in rel["steps"]]
    assert names.index(registry_step(rel["steps"])["name"]) < names.index(
        "Promote tested artifacts to GHCR (digest-pinned)"
    )


def test_kind_deploy_refuses_a_private_registry() -> None:
    steps = load(WORKFLOWS / "pipeline.yml")["jobs"]["integration-deploy"]["steps"]
    guard = steps[0]
    assert guard["if"] == "inputs.integration_registry != ''"
    assert "exit 1" in guard["run"]


def test_build_artifact_uses_registry_instead_of_ttl_sh() -> None:
    action = load(ROOT / "integration-build-artifact" / "action.yml")
    assert action["inputs"]["registry"]["default"] == ""
    builds = [s for s in action["runs"]["steps"] if str(s.get("uses", "")).startswith("octopilot/actions/octopilot@")]
    assert len(builds) == 2
    for b in builds:
        assert b["with"]["registry"] == "${{ inputs.registry }}"
        assert b["with"]["ttl-uuid"] == "${{ inputs.registry == '' && inputs.ttl-uuid || '' }}"
