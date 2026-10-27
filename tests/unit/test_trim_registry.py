"""trim-registry/trim.sh: versions beyond `keep` go, but never the per-platform manifests of a kept multi-arch image.

A fake curl on PATH serves a GHCR package (versions API, token endpoint, manifests) and records every DELETE.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "trim-registry" / "trim.sh"

FAKE_CURL = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
url = next(a for a in args if a.startswith("http"))
state = json.load(open(os.environ["FAKE_STATE"]))
if "-X" in args and args[args.index("-X") + 1] == "DELETE":
    open(os.environ["FAKE_DELETES"], "a").write(url.split("?")[0].rsplit("/", 1)[1] + "\n")
    sys.exit(0)
if "/token?" in url:
    print(json.dumps({"token": "t"})); sys.exit(0)
if "artifactregistry.googleapis.com" in url and "/versions" in url:
    print(json.dumps({"versions": [
        {"name": "projects/p/locations/europe/repositories/r/packages/x/versions/" + v["name"],
         "updateTime": v["updated_at"],
         "relatedTags": [{"name": "projects/p/locations/europe/repositories/r/packages/x/tags/" + t}
                         for t in v["metadata"]["container"]["tags"]]}
        for v in state["versions"]]})); sys.exit(0)
if "/versions" in url:
    print(json.dumps(state["versions"])); sys.exit(0)
if "/manifests/" in url:
    digest = url.rsplit("/", 1)[1]
    if digest in state.get("unreadable", []):
        sys.stderr.write("curl: (22) 404\n"); sys.exit(22)
    kids = state.get("index", {}).get(digest)
    body = {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [{"digest": k} for k in kids]} \
        if kids is not None else {"mediaType": "application/vnd.oci.image.manifest.v1+json", "layers": []}
    print(json.dumps(body)); sys.exit(0)
sys.stderr.write("unexpected " + url + "\n"); sys.exit(2)
"""


def version(vid: int, digest: str, tags: list[str], when: str) -> dict:
    return {"id": vid, "name": digest, "updated_at": when, "metadata": {"container": {"tags": tags}}}


def run(tmp_path: Path, state: dict, keep: int, pushing: str, gar: bool = False) -> list[int]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "state.json").write_text(json.dumps(state))
    deletes = tmp_path / "deletes"
    deletes.write_text("")
    result = tmp_path / "build_result.json"
    src = "localhost:5000" if gar else "ghcr.io/o"
    dst = "europe-docker.pkg.dev/p/r" if gar else "ghcr.io/o"
    result.write_text(
        json.dumps({"builds": [{"imageName": "provider:v0.1.6", "tag": f"{src}/provider:v0.1.6@{pushing}"}]})
    )
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_STATE": str(tmp_path / "state.json"),
        "FAKE_DELETES": str(deletes),
        "BUILD_RESULT": str(result),
        "SRC_REGISTRY": src,
        "DST_REGISTRY": dst,
        "ACCESS_TOKEN": "gar",
        "KEEP": str(keep),
        "GITHUB_TOKEN": "gh",
    }
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=True)
    assert "trim:" in out.stdout
    ids = {v["name"]: v["id"] for v in state["versions"]}
    return sorted(int(x) if x.isdigit() else ids[x] for x in deletes.read_text().split())


def package() -> dict:
    """Three multi-arch releases (an index and two platform manifests each) and one orphan."""
    v = []
    for n, (rel, day) in enumerate([("5", "05"), ("4", "04"), ("3", "03")]):
        base = 10 * (n + 1)
        v.append(version(base, f"sha256:i{rel}", [f"v0.1.{rel}"], f"2026-10-{day}T00:00:00Z"))
        v.append(version(base + 1, f"sha256:a{rel}", [], f"2026-10-{day}T00:00:00Z"))
        v.append(version(base + 2, f"sha256:b{rel}", [], f"2026-10-{day}T00:00:00Z"))
    v.append(version(99, "sha256:orphan", [], "2026-10-01T00:00:00Z"))
    index = {f"sha256:i{r}": [f"sha256:a{r}", f"sha256:b{r}"] for r in "543"}
    return {"versions": v, "index": index}


def test_keeps_the_platform_manifests_of_kept_indexes(tmp_path: Path) -> None:
    # keep 2 = the version being pushed (i6) + v0.1.5 with its two platform manifests
    deleted = run(tmp_path, package(), keep=2, pushing="sha256:i6")
    assert deleted == [20, 21, 22, 30, 31, 32, 99]  # v0.1.4, v0.1.3 and their platforms, the orphan


def test_unreadable_kept_manifest_spares_every_untagged_version(tmp_path: Path) -> None:
    state = package()
    state["unreadable"] = ["sha256:i5"]
    deleted = run(tmp_path, state, keep=2, pushing="sha256:i6")
    assert deleted == [20, 30]  # only the tagged releases beyond keep


def test_keep_zero_deletes_nothing(tmp_path: Path) -> None:
    assert run(tmp_path, package(), keep=0, pushing="sha256:i6") == []


def test_artifact_registry_keeps_the_platform_manifests_of_kept_indexes(tmp_path: Path) -> None:
    deleted = run(tmp_path, package(), keep=2, pushing="sha256:i6", gar=True)
    assert deleted == [20, 21, 22, 30, 31, 32, 99]
