#!/usr/bin/env python3
"""Plan a library release: pick the commit, check it is green, work out vX.Y.Z and write the release notes.

A library release tags a commit that is already on the release branch and has already passed CI. Nothing is
committed or pushed to a branch, so it works on protected branches and on forks that track an upstream. The tag is
the version: git consumers pin `tag = "vX.Y.Z"`.

`release.py plan`: BRANCH, REF (optional commit; default the branch head), BUMP (patch|minor|major), VERSION (optional
exact X.Y.Z[-pre]), GITHUB_REPOSITORY, GITHUB_TOKEN, GITHUB_RUN_ID. Checks out the commit; outputs sha, version, tag,
previous_tag, prerelease.
`release.py notes`: TAG, PREVIOUS_TAG, SHA, NOTES_FILE. Writes NOTES_FILE (keeping notes a generator already wrote).
Run from the root of a full clone (fetch-depth: 0).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
OK_CONCLUSIONS = {"success", "skipped", "neutral"}

# Words that must not appear in release notes, stored as SHA-256 of the lower-cased word so the names themselves are
# not in this public code. A line of notes containing one is dropped. Words that are part of the repository's own name
# are allowed. Add a word:
#   python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].lower().encode()).hexdigest())' WORD
DENY_SHA256 = {
    "a2286bfe26a08085addbda4e35c649fe884c8b6ce645f826740a42613bbdd6aa",
    "b350c93ba398d24b912a9f81380d8ea9ac3402ea70fac52be07a0b7f34b32ff6",
    "30c952fab122c3f9759f02a6d95c3758b246b4fee239957b2d4fee46e26170c4",
    "d0c04f4b1951e4aeaaec8223ed2039e542f3aae805a6fa7f6d794e5afff5d272",
    "f0bf2737126c9e48127426c57e477fd6a2336c79939906b77adb82cefc6cd605",
    "5b863c92caa285b4026ddce6818237e4c0be5bfdb3643f76b0c33d85f074bde8",
}


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, check=check, capture_output=True, text=True).stdout.strip()


def fail(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def parse(v: str):
    m = SEMVER.match(v.strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor), int(patch), pre)


def key(p):
    # A release sorts above its prereleases; prereleases compare by their identifiers.
    major, minor, patch, pre = p
    if pre is None:
        return (major, minor, patch, 1, ())
    ids = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre.split("."))
    return (major, minor, patch, 0, ids)


def fmt(p) -> str:
    major, minor, patch, pre = p
    return f"{major}.{minor}.{patch}" + (f"-{pre}" if pre else "")


def bump(p, kind: str):
    major, minor, patch, _ = p
    if kind == "major":
        return (major + 1, 0, 0, None)
    if kind == "minor":
        return (major, minor + 1, 0, None)
    if kind == "patch":
        return (major, minor, patch + 1, None)
    fail(f"bump must be patch, minor or major, not {kind!r}")


def cargo_version() -> tuple | None:
    """The version in the root Cargo.toml ([workspace.package] or [package])."""
    path = Path("Cargo.toml")
    if not path.is_file():
        return None
    section = ""
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("["):
            section = s.strip("[]").strip()
            continue
        if section in ("package", "workspace.package"):
            m = re.match(r'^version\s*=\s*"([^"]+)"', s)
            if m and parse(m.group(1)):
                found[section] = parse(m.group(1))
    return found.get("workspace.package") or found.get("package")


def api(path: str) -> list | dict:
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(
        f"{base}{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def gate(repo: str, sha: str) -> None:
    """Every check on the commit has finished and passed (the newest run of each check counts), and at least one
    passed. This run's own jobs are left out."""
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    runs = []
    page = 1
    while True:
        data = api(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
        runs += data.get("check_runs", [])
        if len(data.get("check_runs", [])) < 100:
            break
        page += 1
    runs = [r for r in runs if not (run_id and f"/actions/runs/{run_id}/" in (r.get("details_url") or ""))]
    latest: dict[str, dict] = {}
    for r in sorted(runs, key=lambda r: (r.get("started_at") or "", r["id"])):
        latest[r["name"]] = r
    bad = [
        f"{n} ({r['status']}/{r.get('conclusion')})"
        for n, r in latest.items()
        if r["status"] != "completed" or r.get("conclusion") not in OK_CONCLUSIONS
    ]
    statuses = api(f"/repos/{repo}/commits/{sha}/status")
    if statuses.get("total_count", 0) and statuses.get("state") != "success":
        bad.append(f"commit status {statuses.get('state')}")
    if bad:
        fail(f"{sha[:12]} is not green: " + ", ".join(sorted(bad)))
    if not any(r.get("conclusion") == "success" for r in latest.values()):
        fail(f"{sha[:12]} has no passing check yet; release a commit CI has tested")
    print(f"Gate: {sha[:12]} green ({len(latest)} checks)")


def v_tags() -> dict[str, tuple]:
    out = {}
    for t in sh("git", "tag", "-l", "v[0-9]*").splitlines():
        p = parse(t)
        if p and t.startswith("v"):
            out[t] = p
    return out


def is_ancestor(a: str, b: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b]).returncode == 0


def classify(subject: str, body: str) -> str:
    m = re.match(r"^(\w+)(\(([^)]*)\))?(!)?:\s*(.*)$", subject)
    kind, scope, bang = (m.group(1).lower(), (m.group(3) or "").lower(), m.group(4)) if m else ("", "", None)
    if bang or "BREAKING CHANGE" in body or "BREAKING-CHANGE" in body:
        return "Breaking changes"
    deps = re.match(r"^(build|chore)\(deps", subject) or re.match(r"^[Bb]ump \S+ from ", subject)
    if scope == "deps" or kind == "deps" or deps:
        return "Dependencies"
    if kind in ("feat", "feature"):
        return "Features"
    if kind in ("fix", "bugfix", "perf"):
        return "Fixes"
    if not m:
        low = subject.lower()
        if low.startswith(("fix", "correct", "repair")):
            return "Fixes"
        if low.startswith(("add", "support", "implement", "introduce")):
            return "Features"
    return "Other"


SECTIONS = ("Breaking changes", "Features", "Fixes", "Dependencies", "Other")


def structured_notes(repo: str, tag: str, prev: str | None, sha: str) -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    if not prev:
        return (
            f"First tagged release of `{repo.split('/')[-1]}`, at {sha[:12]}.\n\n"
            f"Earlier changes are in the [commit history]({server}/{repo}/commits/{sha}).\n"
        )
    log = sh("git", "log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e", f"{prev}..{sha}")
    groups: dict[str, list[str]] = {s: [] for s in SECTIONS}
    count = 0
    for rec in log.split("\x1e"):
        rec = rec.strip()
        if not rec:
            continue
        h, subject, body = [*rec.split("\x1f"), "", ""][:3]
        count += 1
        groups[classify(subject, body)].append(f"- {subject} ({h[:8]})")
    lines = [
        f"{count} commit{'s' if count != 1 else ''} since {prev} ([compare]({server}/{repo}/compare/{prev}...{tag})).",
        "",
    ]
    for s in SECTIONS:
        if groups[s]:
            lines += [f"### {s}", ""] + groups[s] + [""]
    return "\n".join(lines)


def sanitise(text: str, repo: str) -> str:
    own = set(re.findall(r"[a-z0-9]+", repo.split("/")[-1].lower()))
    kept, dropped = [], 0
    for line in text.splitlines():
        words = set(re.findall(r"[a-z0-9]+", line.lower())) - own
        if any(hashlib.sha256(w.encode()).hexdigest() in DENY_SHA256 for w in words):
            dropped += 1
            continue
        kept.append(line)
    if dropped:
        print(f"::warning::release notes: {dropped} line(s) left out (they named a downstream project)")
    # Drop headings left with nothing under them.
    out: list[str] = []
    for i, line in enumerate(kept):
        if line.startswith("#"):
            rest = kept[i + 1 :]
            nxt = next((r for r in rest if r.strip()), None)
            if nxt is None or (nxt.startswith("#") and nxt.count("#") <= line.split(" ")[0].count("#")):
                continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def write_outputs(out: dict) -> None:
    print(json.dumps(out))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            for k, v in out.items():
                f.write(f"{k}={v}\n")


def next_version(tags: dict, cargo, kind: str, explicit: str):
    if explicit:
        return parse(explicit) or fail(f"version {explicit!r} is not X.Y.Z[-pre]")
    if not tags:
        # First release: the version the manifest declares, without a prerelease suffix.
        base = cargo or (0, 1, 0, None)
        return (base[0], base[1], base[2], None)
    floor = max(list(tags.values()) + ([cargo] if cargo else []), key=key)
    core = (floor[0], floor[1], floor[2], None)
    # 1.2.0-rc.1 -> patch -> 1.2.0; otherwise bump.
    return core if (floor[3] is not None and kind == "patch") else bump(core, kind)


def plan() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("BRANCH", "").strip() or fail("BRANCH is required")
    ref = os.environ.get("REF", "").strip()
    kind = os.environ.get("BUMP", "patch").strip() or "patch"
    explicit = os.environ.get("VERSION", "").strip()

    sh("git", "fetch", "--force", "--tags", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    head = f"refs/remotes/origin/{branch}"
    sha = sh("git", "rev-parse", "--verify", "--quiet", f"{ref or head}^{{commit}}", check=False)
    if not sha:
        fail(f"unknown ref {ref!r}")
    if not is_ancestor(sha, head):
        fail(f"{sha[:12]} is not on {branch}; only commits on the release branch are released")
    tags = v_tags()
    existing = [t for t in sh("git", "tag", "--points-at", sha).splitlines() if t in tags]
    if existing:
        fail(f"{sha[:12]} is already released as {', '.join(existing)}")

    if os.environ.get("SKIP_GATE") != "true":
        gate(repo, sha)

    sh("git", "checkout", "--quiet", "--detach", sha)
    new = next_version(tags, cargo_version(), kind, explicit)
    tag = f"v{fmt(new)}"
    highest = max(tags, key=lambda t: key(tags[t])) if tags else None
    if tag in tags:
        fail(f"{tag} already exists")
    if highest and key(new) <= key(tags[highest]):
        fail(f"{tag} is not above the highest release {highest}")
    # Versions only go up along the branch: the newest release on it must be an ancestor of the commit released.
    if highest and is_ancestor(highest, head) and not is_ancestor(highest, sha):
        fail(f"{sha[:12]} is older than {highest}; release a commit after it")
    reachable = [t for t in tags if is_ancestor(t, sha)]
    prev = max(reachable, key=lambda t: key(tags[t])) if reachable else ""
    write_outputs(
        {"sha": sha, "version": fmt(new), "tag": tag, "previous_tag": prev, "prerelease": "true" if new[3] else "false"}
    )


def notes() -> None:
    """Keep notes a generator already wrote to NOTES_FILE, else write the structured changelog; then sanitise."""
    repo = os.environ["GITHUB_REPOSITORY"]
    path = Path(os.environ.get("NOTES_FILE", "release-notes.md"))
    tag, prev, sha = os.environ["TAG"], os.environ.get("PREVIOUS_TAG", "").strip() or None, os.environ["SHA"]
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        path.write_text(structured_notes(repo, tag, prev, sha), encoding="utf-8")
    path.write_text(sanitise(path.read_text(encoding="utf-8"), repo), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    {"plan": plan, "notes": notes}[sys.argv[1] if len(sys.argv) > 1 else "plan"]()
