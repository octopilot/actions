"""Release builds version the chart from the tag, so the chart pushed as <chart>:vX.Y.Z says version X.Y.Z (Flux's
helm-controller rejects a mismatch) and defaults to the image released under the same tag."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STAMP = ROOT / "common" / "stamp-chart-version.sh"

CHART = """apiVersion: v2
name: igniteflux
description: test
version: 0.1.0
appVersion: "0.1.0"
dependencies:
  - name: common
    version: 2.0.0
    repository: oci://example
"""


def stamp(tmp_path: Path, tag: str, chart: str = CHART) -> dict:
    (tmp_path / "Chart.yaml").write_text(chart)
    subprocess.run(
        ["bash", str(STAMP), str(tmp_path), tag],
        check=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"]},
    )
    return yaml.safe_load((tmp_path / "Chart.yaml").read_text())


def test_release_tag_sets_version_and_app_version(tmp_path: Path) -> None:
    got = stamp(tmp_path, "v0.1.1")
    assert got["version"] == "0.1.1"
    assert got["appVersion"] == "v0.1.1", "the tag the images are released under"
    assert got["dependencies"][0]["version"] == "2.0.0", "dependency versions untouched"
    assert got["name"] == "igniteflux"


@pytest.mark.parametrize(
    ("tag", "version"), [("v1.2.3-rc.1", "1.2.3-rc.1"), ("2.0.0", "2.0.0"), ("v1.0.0+b5", "1.0.0+b5")]
)
def test_semver_tags(tmp_path: Path, tag: str, version: str) -> None:
    assert stamp(tmp_path, tag)["version"] == version


def test_missing_keys_are_added(tmp_path: Path) -> None:
    got = stamp(tmp_path, "v3.0.0", "apiVersion: v2\nname: x\n")
    assert got["version"] == "3.0.0"
    assert got["appVersion"] == "v3.0.0"


@pytest.mark.parametrize("tag", ["main", "v1.2", "release-5", "v01.2.3"])
def test_non_release_tags_leave_the_chart_alone(tmp_path: Path, tag: str) -> None:
    (tmp_path / "Chart.yaml").write_text(CHART)
    subprocess.run(["bash", str(STAMP), str(tmp_path), tag], check=True, capture_output=True)
    assert (tmp_path / "Chart.yaml").read_text() == CHART


def test_missing_chart_fails(tmp_path: Path) -> None:
    out = subprocess.run(["bash", str(STAMP), str(tmp_path), "v1.0.0"], capture_output=True, text=True)
    assert out.returncode != 0


def test_integration_build_stamps_charts_on_tag_builds() -> None:
    action = yaml.safe_load((ROOT / "integration-build-artifact" / "action.yml").read_text())
    names = [s.get("name", "") for s in action["runs"]["steps"]]
    stamp_step = next(s for s in action["runs"]["steps"] if "stamp-chart-version.sh" in s.get("run", ""))
    assert "github.ref_type == 'tag'" in stamp_step["if"]
    assert names.index(stamp_step["name"]) < names.index("Build and push chart (Octopilot)")
