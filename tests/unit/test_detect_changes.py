"""Change detection (detect-contexts/changes.py) on a two-suite Rust workspace in a real git repository."""

import json
import os
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../detect-contexts")))

import changes
import detect

LOCK = """version = 3

[[package]]
name = "crm_pipeline"
version = "0.1.0"
dependencies = ["shared", "serde"]

[[package]]
name = "acc_ledger"
version = "0.1.0"
dependencies = ["ledger_core", "{tokio}"]

[[package]]
name = "ledger_core"
version = "0.1.0"
dependencies = ["serde"]

[[package]]
name = "shared"
version = "0.1.0"

[[package]]
name = "serde"
version = "1.0.200"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "tokio"
version = "{tokio_version}"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""


def lock(tokio_version="1.40.0"):
    return LOCK.replace("{tokio}", "tokio").replace("{tokio_version}", tokio_version)


def crate(root, rel, name):
    d = root / rel
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "0.1.0"\n')
    (d / "src" / "lib.rs").write_text("// x\n")


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def sha(root):
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


SKAFFOLD = {
    "apiVersion": "skaffold/v4beta7",
    "kind": "Config",
    "build": {
        "artifacts": [
            {
                "image": "ghcr.io/x/app-crm",
                "context": ".",
                "buildpacks": {
                    "builder": "b",
                    "env": [
                        "BP_RUST_WORKSPACE_DIR=ms",
                        "BP_RUST_PACKAGES=crm_pipeline",
                        "BP_SUITE_IMAGES=suites/crm.txt",
                        "BP_TEST_COMMAND=cargo test -p crm_pipeline",
                    ],
                },
            },
            {
                "image": "ghcr.io/x/app-accounting",
                "context": ".",
                "buildpacks": {
                    "builder": "b",
                    "env": [
                        "BP_RUST_WORKSPACE_DIR=ms",
                        "BP_RUST_PACKAGES=acc_ledger",
                        "BP_SUITE_IMAGES=suites/accounting.txt",
                        "BP_TEST_COMMAND=cargo test -p acc_ledger",
                    ],
                    "dependencies": {"paths": ["openapi/accounting/**"]},
                },
            },
            {"image": "ghcr.io/x/app-chart", "context": "helm/chart", "buildpacks": {"builder": "b"}},
        ]
    },
}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ms").mkdir()
    (root / "ms" / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crm/pipeline", "acc/ledger", "acc/core", "shared"]\n'
    )
    crate(root, "ms/crm/pipeline", "crm_pipeline")
    crate(root, "ms/acc/ledger", "acc_ledger")
    crate(root, "ms/acc/core", "ledger_core")
    crate(root, "ms/shared", "shared")
    (root / "ms" / "Cargo.lock").write_text(lock())
    (root / "suites").mkdir()
    (root / "suites" / "crm.txt").write_text("pipeline ghcr.io/x/app-crm-pipeline\n")
    (root / "suites" / "accounting.txt").write_text("ledger ghcr.io/x/app-acc-ledger\n")
    (root / "openapi" / "accounting").mkdir(parents=True)
    (root / "openapi" / "accounting" / "ledger.yaml").write_text("openapi: 3.1.0\n")
    (root / "helm" / "chart").mkdir(parents=True)
    (root / "helm" / "chart" / "Chart.yaml").write_text("name: chart\nversion: 0.1.0\n")
    (root / "README.md").write_text("x\n")
    (root / "skaffold.yaml").write_text(yaml.safe_dump(SKAFFOLD))
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return root


def run(root, event_name="push", before=None, ref="refs/heads/main", extra=None):
    ev = root.parent / "event.json"
    ev.write_text(json.dumps({"before": before or ""}))
    env = {"GITHUB_EVENT_NAME": event_name, "GITHUB_EVENT_PATH": str(ev), "GITHUB_REF": ref, "GITHUB_SHA": sha(root)}
    env.update(extra or {})
    cfg = yaml.safe_load((root / "skaffold.yaml").read_text())
    ctx = detect.build_pipeline_context(cfg, str(root))
    return changes.filter_context(ctx, cfg["build"]["artifacts"], str(root), "skaffold.yaml", env)


def commit(root, path, text="// changed\n"):
    base = sha(root)
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", f"change {path}")
    return base


def images(ctx):
    return sorted(e["image"] for e in ctx["integration_matrix"] if e.get("type") == "image")


def covered(ctx):
    return sorted(c for e in ctx["matrix"] if e.get("kind") == "test" for c in e.get("artifacts", [e.get("name")]))


def test_a_suite_change_builds_that_suite_only(repo):
    before = commit(repo, "ms/crm/pipeline/src/lib.rs")
    ctx = run(repo, before=before)
    assert images(ctx) == ["ghcr.io/x/app-crm"]
    assert "ghcr.io/x/app-crm" in covered(ctx) and "ghcr.io/x/app-accounting" not in covered(ctx)
    assert ctx["change_detection"]["skipped"]["ghcr.io/x/app-accounting"] == "no change to its inputs"


def test_a_shared_crate_rebuilds_only_its_dependents(repo):
    before = commit(repo, "ms/acc/core/src/lib.rs")
    assert images(run(repo, before=before)) == ["ghcr.io/x/app-accounting"]
    before = commit(repo, "ms/shared/src/lib.rs")
    assert images(run(repo, before=before)) == ["ghcr.io/x/app-crm"]


def test_lockfile_counts_per_suite(repo):
    before = commit(repo, "ms/Cargo.lock", lock("1.41.0"))
    ctx = run(repo, before=before)
    assert images(ctx) == ["ghcr.io/x/app-accounting"]
    assert "tokio" in ctx["change_detection"]["changed"]["ghcr.io/x/app-accounting"]


def test_declared_paths_and_the_suite_map_are_inputs(repo):
    before = commit(repo, "openapi/accounting/ledger.yaml", "openapi: 3.1.1\n")
    assert images(run(repo, before=before)) == ["ghcr.io/x/app-accounting"]
    before = commit(repo, "suites/crm.txt", "pipeline ghcr.io/x/other\n")
    assert images(run(repo, before=before)) == ["ghcr.io/x/app-crm"]


def test_docs_build_nothing_and_charts_build_alone(repo):
    before = commit(repo, "README.md", "y\n")
    ctx = run(repo, before=before)
    assert images(ctx) == [] and ctx["matrix"] == []
    before = commit(repo, "helm/chart/values.yaml", "a: 1\n")
    ctx = run(repo, before=before)
    assert images(ctx) == ["ghcr.io/x/app-chart"]
    assert any(e.get("language") == "helm" for e in ctx["matrix"])


def test_global_inputs_build_everything(repo):
    before = commit(repo, ".github/workflows/ci.yml", "on: push\n")
    assert len(images(run(repo, before=before))) == 3
    before = commit(repo, "tooling/x.py", "x = 1\n")
    assert len(images(run(repo, before=before, extra={"ALWAYS_REBUILD_PATHS": "tooling/**"}))) == 3


def test_no_range_builds_everything(repo):
    assert len(images(run(repo, event_name="workflow_dispatch"))) == 3
    assert len(images(run(repo, before="0" * 40))) == 3
    commit(repo, "ms/crm/pipeline/src/lib.rs")
    assert len(images(run(repo, extra={"BUILD_ALL": "true"}))) == 3


def test_a_tag_compares_the_previous_tag(repo):
    git(repo, "tag", "v0.1.0")
    commit(repo, "ms/crm/pipeline/src/lib.rs")
    commit(repo, "README.md", "z\n")
    git(repo, "tag", "v0.1.1")
    ctx = run(repo, event_name="workflow_dispatch", ref="refs/tags/v0.1.1")
    assert images(ctx) == ["ghcr.io/x/app-crm"]
    assert "since v0.1.0" in ctx["change_detection"]["range"]


def test_a_pull_request_compares_its_merge_base(repo):
    base = sha(repo)
    git(repo, "checkout", "-qb", "feature")
    commit(repo, "ms/acc/ledger/src/lib.rs")
    ev = repo.parent / "event.json"
    ev.write_text(json.dumps({"pull_request": {"base": {"sha": base}}}))
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(ev),
        "GITHUB_REF": "refs/pull/1/merge",
        "GITHUB_SHA": sha(repo),
    }
    cfg = yaml.safe_load((repo / "skaffold.yaml").read_text())
    ctx = changes.filter_context(
        detect.build_pipeline_context(cfg, str(repo)), cfg["build"]["artifacts"], str(repo), "skaffold.yaml", env
    )
    assert images(ctx) == ["ghcr.io/x/app-accounting"]


def test_matches():
    assert changes.matches("openapi/a/b.yaml", "openapi/**")
    assert changes.matches("ms/crm/x.rs", "ms/crm")
    assert not changes.matches("ms/crmx/x.rs", "ms/crm")
    assert changes.matches("anything", ".")
