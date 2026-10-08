"""The test action runs where detect-contexts says the toolchain lives (workdir, e.g. a nested Cargo workspace named by
BP_RUST_WORKSPACE_DIR), not in the artifact's build context."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def parse_outputs(tmp_path: Path, item: dict) -> dict:
    steps = yaml.safe_load((ROOT / "test" / "action.yml").read_text())["runs"]["steps"]
    script = next(s for s in steps if s.get("id") == "ctx")["run"]
    out = tmp_path / "out"
    subprocess.run(
        ["bash", "-c", script],
        check=True,
        env={
            "PATH": os.environ["PATH"],
            "PIPELINE_CONTEXT": json.dumps(item),
            "GITHUB_OUTPUT": str(out),
        },
    )
    return dict(line.split("=", 1) for line in out.read_text().splitlines())


@pytest.mark.parametrize(
    ("item", "want"),
    [
        (
            {"language": "rust", "context": ".", "workdir": "microservices"},
            "microservices",
        ),
        ({"language": "rust", "context": "svc"}, "svc"),
        ({"language": "go"}, "."),
    ],
)
def test_runs_in_the_workdir(tmp_path: Path, item: dict, want: str) -> None:
    assert parse_outputs(tmp_path, item)["context"] == want
