"""
Unit tests for integration-build-artifact action contract.

The action parses a single matrix item (artifact JSON) and runs docker, pack, or helm.
These tests exercise the same parsing logic and expected outputs.
"""


def parse_artifact_contract(artifact: dict) -> dict:
    """Parse artifact JSON the same way the action's Parse step does (jq contract)."""
    return {
        "type": artifact.get("type") or "",
        "build_method": artifact.get("build_method") or "",
        "context": artifact.get("context", "."),
        "suffix": artifact.get("suffix") or "",
        "output_key": artifact.get("output_key") or "",
        "path": artifact.get("path") or "",
        "dockerfile": artifact.get("dockerfile", "Dockerfile"),
        "builder": artifact.get("builder", "paketobuildpacks/builder-jammy-base"),
        "build_env": artifact.get("build_env") or "",
    }


def which_step_runs(parsed: dict) -> str:
    """Which build step runs: docker, pack, or helm."""
    if parsed["type"] == "image" and parsed["build_method"] == "docker":
        return "docker"
    if parsed["type"] == "image" and parsed["build_method"] == "pack":
        return "pack"
    if parsed["type"] == "chart":
        return "helm"
    return "none"


class TestParseArtifactContract:
    def test_image_docker_full(self):
        artifact = {
            "type": "image",
            "build_method": "docker",
            "context": ".",
            "suffix": "monitor",
            "output_key": "image_monitor",
            "dockerfile": "Dockerfile",
        }
        p = parse_artifact_contract(artifact)
        assert p["type"] == "image"
        assert p["build_method"] == "docker"
        assert p["suffix"] == "monitor"
        assert which_step_runs(p) == "docker"

    def test_image_pack_full(self):
        artifact = {
            "type": "image",
            "build_method": "pack",
            "context": "tests/integration/cronjob-app",
            "suffix": "cronjob",
            "output_key": "image_cronjob",
            "builder": "paketobuildpacks/builder-jammy-base",
            "build_env": "BP_JVM_VERSION=17",
        }
        p = parse_artifact_contract(artifact)
        assert p["type"] == "image"
        assert p["build_method"] == "pack"
        assert "BP_JVM_VERSION=17" in p["build_env"]
        assert which_step_runs(p) == "pack"

    def test_chart_full(self):
        artifact = {"type": "chart", "path": "chart", "output_key": "chart"}
        p = parse_artifact_contract(artifact)
        assert p["type"] == "chart"
        assert p["path"] == "chart"
        assert which_step_runs(p) == "helm"

    def test_empty_artifact_defaults(self):
        p = parse_artifact_contract({})
        assert p["context"] == "."
        assert p["dockerfile"] == "Dockerfile"
        assert which_step_runs(p) == "none"

    def test_image_unknown_build_method_runs_none(self):
        artifact = {"type": "image", "build_method": "custom", "suffix": "x", "output_key": "image_x"}
        p = parse_artifact_contract(artifact)
        assert which_step_runs(p) == "none"
