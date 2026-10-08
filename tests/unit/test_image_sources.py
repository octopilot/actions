"""Image sources: every image the actions pull can come from a configured registry (image_registry /
OCTOPILOT_IMAGE_REGISTRY) and defaults to the value written in the action when unset."""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RESOLVE = ROOT / "common" / "resolve-image.sh"
RUN = ROOT / "common" / "run-action-image.sh"
MIRROR = "us-docker.pkg.dev/pw-ctl/ci"

# Actions whose image used to be `docker://ghcr.io/octopilot/actions/<name>:latest`.
IMAGE_ACTIONS = ["bump-version", "kubernetes-auth", "read-properties", "release", "rotate-secret", "sops-decrypt"]
# Composite actions that pull images themselves (directly or through a nested octopilot action).
PULLING_ACTIONS = [
    *IMAGE_ACTIONS,
    "octopilot",
    "build-ephemeral",
    "integration-build-artifact",
    "test",
    "verify-registry",
    "resolve-image",
]


def resolve(ref: str, *registry: str, env: dict | None = None) -> str:
    environment = {"PATH": os.environ["PATH"], **(env or {})}
    out = subprocess.run(
        ["bash", str(RESOLVE), ref, *registry], capture_output=True, text=True, env=environment, check=True
    )
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("ref", "want"),
    [
        ("ghcr.io/octopilot/op:v1.2.0", f"{MIRROR}/octopilot/op:v1.2.0"),
        ("kindest/node:v1.34.3", f"{MIRROR}/kindest/node:v1.34.3"),
        ("hello-world:latest", f"{MIRROR}/library/hello-world:latest"),
        ("docker.io/alpine:3", f"{MIRROR}/library/alpine:3"),
        ("docker.io/library/alpine:3", f"{MIRROR}/library/alpine:3"),
        ("registry.k8s.io/pause:3.10", f"{MIRROR}/pause:3.10"),
        ("quay.io/org/img@sha256:abc", f"{MIRROR}/org/img@sha256:abc"),
        # never rewritten
        ("localhost:5001/x:dev", "localhost:5001/x:dev"),
        ("127.0.0.1:5001/x", "127.0.0.1:5001/x"),
        ("ttl.sh/uuid-app:1d", "ttl.sh/uuid-app:1d"),
        ("us-docker.pkg.dev/pw-ctl/platform/app:1", "us-docker.pkg.dev/pw-ctl/platform/app:1"),
    ],
)
def test_resolve_with_registry(ref: str, want: str) -> None:
    assert resolve(ref, MIRROR + "/") == want
    assert resolve(ref, env={"OCTOPILOT_IMAGE_REGISTRY": MIRROR}) == want


def test_runner_level_registry_is_the_fallback() -> None:
    runner = {"OCTOPILOT_RUNNER_IMAGE_REGISTRY": MIRROR}
    assert resolve("kindest/node:v1.34.3", env=runner) == f"{MIRROR}/kindest/node:v1.34.3"
    # an empty workflow value (what a composite step's env yields when unset) does not shadow the runner's
    assert (
        resolve("kindest/node:v1.34.3", env={**runner, "OCTOPILOT_IMAGE_REGISTRY": ""})
        == f"{MIRROR}/kindest/node:v1.34.3"
    )
    # the workflow's own value wins
    other = "europe-docker.pkg.dev/p/ci"
    assert (
        resolve("kindest/node:v1.34.3", env={**runner, "OCTOPILOT_IMAGE_REGISTRY": other})
        == f"{other}/kindest/node:v1.34.3"
    )


@pytest.mark.parametrize("ref", ["ghcr.io/octopilot/op:v1.2.0", "kindest/node:v1.34.3", "hello-world:latest"])
def test_resolve_unset_keeps_the_default(ref: str) -> None:
    assert resolve(ref) == ref
    assert resolve(ref, env={"OCTOPILOT_IMAGE_REGISTRY": ""}) == ref
    # an explicit empty argument wins over the environment
    assert resolve(ref, "", env={"OCTOPILOT_IMAGE_REGISTRY": MIRROR}) == ref


def fake_docker(tmp_path: Path) -> Path:
    """A `docker` on PATH that records its arguments, one per line."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$DOCKER_ARGS_FILE"\n')
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_action_image(tmp_path: Path, extra_env: dict) -> list[str]:
    bin_dir = fake_docker(tmp_path)
    temp = tmp_path / "_temp"
    (temp / "_runner_file_commands").mkdir(parents=True)
    workspace = tmp_path / "work"
    workspace.mkdir()
    args_file = tmp_path / "docker-args"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_ARGS_FILE": str(args_file),
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(temp),
        "GITHUB_OUTPUT": str(temp / "_runner_file_commands" / "set_output_1"),
        "GITHUB_ENV": str(temp / "_runner_file_commands" / "set_env_1"),
        "GITHUB_REPOSITORY": "o/r",
        "INPUT_FILE": "test.properties",
        "UNRELATED_SECRET": "must-not-leak",
        **extra_env,
    }
    subprocess.run(["bash", str(RUN), "octopilot/actions/read-properties"], env=env, check=True, capture_output=True)
    return args_file.read_text().splitlines()


def test_run_action_image_defaults_to_ghcr(tmp_path: Path) -> None:
    args = run_action_image(tmp_path, {})
    assert args[-1] == "ghcr.io/octopilot/actions/read-properties:latest"
    assert "GITHUB_WORKSPACE=/github/workspace" in args
    assert f"{tmp_path / 'work'}:/github/workspace" in args
    assert f"{tmp_path / '_temp'}:{tmp_path / '_temp'}" in args, "file commands reachable at their own paths"
    assert "INPUT_FILE" in args
    assert "GITHUB_REPOSITORY" in args
    assert "UNRELATED_SECRET" not in args


def test_run_action_image_uses_the_configured_registry_and_tag(tmp_path: Path) -> None:
    args = run_action_image(
        tmp_path,
        {
            "OCTOPILOT_IMAGE_REGISTRY": MIRROR,
            "OCTOPILOT_ACTION_IMAGE_TAG": "abc-1h",
            "OCTOPILOT_PASS_ENV": "UNRELATED_SECRET",
        },
    )
    assert args[-1] == f"{MIRROR}/octopilot/actions/read-properties:abc-1h"
    assert "UNRELATED_SECRET" in args, "named in OCTOPILOT_PASS_ENV"


def load_action(name: str) -> dict:
    return yaml.safe_load((ROOT / name / "action.yml").read_text())


def test_no_action_pins_an_image_in_its_metadata() -> None:
    for action_yml in ROOT.glob("*/action.yml"):
        runs = yaml.safe_load(action_yml.read_text())["runs"]
        assert runs["using"] != "docker", f"{action_yml.parent.name}: docker actions cannot change their image"


@pytest.mark.parametrize("name", PULLING_ACTIONS)
def test_pulling_actions_take_image_registry(name: str) -> None:
    action = load_action(name)
    spec = action["inputs"]["image_registry"]
    assert spec.get("default", "") == "", "unset must mean: use the image written in the action"
    text = (ROOT / name / "action.yml").read_text()
    assert "inputs.image_registry || env.OCTOPILOT_IMAGE_REGISTRY" in text, "falls back to the job's environment"


@pytest.mark.parametrize("name", IMAGE_ACTIONS)
def test_image_actions_run_their_own_image(name: str) -> None:
    text = (ROOT / name / "action.yml").read_text()
    assert f'run-action-image.sh" octopilot/actions/{name}' in text


def test_nested_calls_pass_image_registry_down() -> None:
    """Every call from one of our composite actions or reusable workflows to a pulling action passes image_registry."""
    # Composite actions and the reusable workflows callers adopt (this repo's own CI is not part of the contract).
    workflows = ROOT / ".github" / "workflows"
    files = [*ROOT.glob("*/action.yml"), workflows / "pipeline.yml", workflows / "integration-artifacts-wave.yml"]
    missing = []
    for f in files:
        doc = yaml.safe_load(f.read_text())
        steps = []
        if "runs" in doc:
            steps = doc["runs"].get("steps", [])
        for job in (doc.get("jobs") or {}).values():
            steps += job.get("steps", [])
            uses = job.get("uses", "")
            if "integration-artifacts-wave.yml" in uses and "image_registry" not in (job.get("with") or {}):
                missing.append(f"{f.relative_to(ROOT)}: job uses {uses}")
        for step in steps:
            uses = step.get("uses", "")
            target = uses.split("@")[0].removeprefix("octopilot/actions/").removeprefix("./")
            if target in PULLING_ACTIONS and "image_registry" not in (step.get("with") or {}):
                missing.append(f"{f.relative_to(ROOT)}: {uses}")
    assert not missing, "calls that drop image_registry:\n" + "\n".join(missing)
