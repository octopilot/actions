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


def refreshing(tmp_path: Path, **env: str) -> tuple[int, dict, dict, str]:
    """Run the refreshing-credentials step; returns (exit code, outputs, GITHUB_ENV entries, stdout+stderr)."""
    steps = load(ROOT / "integration-registry" / "action.yml")["runs"]["steps"]
    step = next(s for s in steps if s.get("id") == "refreshing")
    out, genv, temp = tmp_path / "out", tmp_path / "env", tmp_path / "temp"
    out.write_text("")
    genv.write_text("")
    temp.mkdir()
    base = {"WIP": WIP, "SA": SA, "RUNNER_TEMP": str(temp), "GITHUB_JOB": "integration-artifacts"}
    proc = subprocess.run(
        ["bash", "-c", step["run"]],
        env={"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out), "GITHUB_ENV": str(genv), **base, **env},
        capture_output=True,
        text=True,
    )
    parse = lambda p: dict(line.split("=", 1) for line in p.read_text().splitlines() if "=" in line)  # noqa: E731
    return proc.returncode, parse(out), parse(genv), proc.stdout + proc.stderr


def test_refreshing_credentials_are_an_external_account_outside_the_checkout(tmp_path: Path) -> None:
    import json
    import stat

    code, outputs, genv, text = refreshing(
        tmp_path,
        ACTIONS_ID_TOKEN_REQUEST_URL="https://token.actions.example/id?api-version=2.0",
        ACTIONS_ID_TOKEN_REQUEST_TOKEN="job-request-token",
    )
    assert code == 0, text
    path = Path(outputs["path"])
    assert genv["OCTOPILOT_GOOGLE_CREDENTIALS"] == str(path)
    assert path.parent == tmp_path / "temp", "RUNNER_TEMP, never the checkout (the build context)"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    cfg = json.loads(path.read_text())
    assert cfg["type"] == "external_account"
    assert cfg["audience"] == f"//iam.googleapis.com/{WIP}"
    assert cfg["token_url"] == "https://sts.googleapis.com/v1/token"
    assert cfg["service_account_impersonation_url"].endswith(f"/serviceAccounts/{SA}:generateAccessToken")
    src = cfg["credential_source"]
    assert src["url"].startswith("https://token.actions.example/id?api-version=2.0&audience=https%3A%2F%2Fiam.googleapis.com%2F")
    assert src["headers"]["Authorization"] == "Bearer job-request-token"
    assert src["format"] == {"type": "json", "subject_token_field_name": "value"}
    assert "job-request-token" not in text, "the request token must not be printed"


def test_refreshing_credentials_skip_without_an_oidc_endpoint(tmp_path: Path) -> None:
    code, outputs, genv, text = refreshing(tmp_path)
    assert code == 0
    assert "path" not in outputs and "OCTOPILOT_GOOGLE_CREDENTIALS" not in genv
    assert "::warning::" in text


def test_refreshing_credentials_follow_the_wif_login() -> None:
    steps = load(ROOT / "integration-registry" / "action.yml")["runs"]["steps"]
    ids = [s.get("id") for s in steps]
    step = steps[ids.index("refreshing")]
    assert ids.index("gcp") < ids.index("refreshing")
    assert step["if"] == "steps.gcp.outcome == 'success'"


def test_op_gets_the_refreshing_credentials_and_tunables() -> None:
    step = load(ROOT / "octopilot" / "action.yml")["runs"]["steps"][0]
    run, env = step["run"], step["env"]
    assert env["OP_PROPAGATION_TIMEOUT"] == "${{ inputs.propagation_timeout || env.OCTOPILOT_PROPAGATION_TIMEOUT || '10m' }}"
    assert env["OP_FANOUT_PARALLEL"] == "${{ inputs.fanout_parallel || env.OCTOPILOT_FANOUT_PARALLEL || '6' }}"
    # Passed by name (not on the docker command line, where ps would show it) and materialised in the container.
    for name in ("GOOGLE_CREDENTIALS_CONTENT", "OP_PROPAGATION_TIMEOUT", "OP_FANOUT_PARALLEL"):
        assert f"-e {name} \\" in run
    assert "export GOOGLE_APPLICATION_CREDENTIALS=/tmp/.gcp/credentials.json" in run
    assert 'export GOOGLE_APPLICATION_CREDENTIALS="${OCTOPILOT_GOOGLE_CREDENTIALS}"' in run  # build_bypass


def test_pipeline_passes_propagation_timeout_and_fanout_parallel() -> None:
    pipe = load(WORKFLOWS / "pipeline.yml")
    inputs = pipe[True]["workflow_call"]["inputs"]
    assert inputs["propagation_timeout"]["default"] == "10m"
    assert inputs["suite_fanout_parallel"]["default"] == 6
    build = next(s for s in pipe["jobs"]["integration-artifacts"]["steps"] if s.get("name") == "Build and push artifact")
    assert build["with"]["propagation_timeout"] == "${{ inputs.propagation_timeout }}"
    assert build["with"]["fanout_parallel"] == "${{ inputs.suite_fanout_parallel }}"
    wave = pipe["jobs"]["integration-artifacts-wave1"]["with"]
    assert wave["propagation_timeout"] == "${{ inputs.propagation_timeout }}"
    assert wave["suite_fanout_parallel"] == "${{ inputs.suite_fanout_parallel }}"
    wbuild = next(
        s for s in load(WORKFLOWS / "integration-artifacts-wave.yml")["jobs"]["build"]["steps"]
        if s.get("name") == "Build and push artifact"
    )
    assert wbuild["with"]["propagation_timeout"] == "${{ inputs.propagation_timeout }}"
    action = load(ROOT / "integration-build-artifact" / "action.yml")
    builds = [s for s in action["runs"]["steps"] if str(s.get("uses", "")).startswith("octopilot/actions/octopilot@")]
    assert all(b["with"]["propagation_timeout"] == "${{ inputs.propagation_timeout }}" for b in builds)
