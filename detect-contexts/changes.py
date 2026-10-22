"""Change detection for detect-contexts: which skaffold artifacts a commit range touches.

Opt-in (ONLY_CHANGED=true). Each artifact's inputs are worked out, the commit range's changed files are listed, and
every matrix leg whose inputs saw no change is dropped, so a multi-suite repo builds only the suites a change touches,
side by side.

Inputs of an artifact:
- Rust buildpack artifacts with BP_RUST_PACKAGES: the directories of those workspace packages and of every workspace
  package they depend on (transitively, from Cargo.lock), plus their workspace's Cargo.toml and rust-toolchain file.
  The lockfile counts per artifact: the artifact is changed when the set of external crates (name, version, source)
  in its dependency closure differs between the two ends of the range, so a bump that only another suite uses does
  not rebuild it.
- Rust artifacts without BP_RUST_PACKAGES (the whole workspace), and every other artifact: their context directory.
- skaffold's own buildpacks.dependencies.paths (globs, relative to the context), added to the above, and
  buildpacks.dependencies.ignore, taken away.
- The file named by BP_SUITE_IMAGES (the artifact's fan-out map).

Global inputs rebuild everything: the skaffold file, .github/workflows/**, and ALWAYS_REBUILD_PATHS (comma or newline
separated globs).

Commit range: a push compares the previous head (event.before) with this one; a pull request compares the merge
base with the head; a tag (pushed, or a workflow_dispatch on a tag ref) compares the previous tag matching the same
prefix. Anything else (a dispatch on a branch, a new branch, history that cannot be read, BUILD_ALL=true) builds
everything.
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import subprocess
import sys
import tomllib

ZERO_SHA = "0" * 40
GLOBAL_PATTERNS = (".github/workflows/**",)


# ----------------------------------------------------------------------------------------------------- git


def _git(repo_root: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", repo_root, *args], check=True, capture_output=True, text=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return out.stdout


def _has_commit(repo_root: str, sha: str) -> bool:
    if _git(repo_root, "cat-file", "-e", f"{sha}^{{commit}}") is not None:
        return True
    # shallow checkouts: fetch just that commit
    _git(repo_root, "fetch", "--no-tags", "--depth=200", "origin", sha)
    return _git(repo_root, "cat-file", "-e", f"{sha}^{{commit}}") is not None


def commit_range(repo_root: str, env: dict[str, str]) -> tuple[str | None, str, str]:
    """(base, head, why): base None = build everything, why says which range or why not."""
    head = env.get("GITHUB_SHA") or (_git(repo_root, "rev-parse", "HEAD") or "").strip()
    if env.get("BUILD_ALL", "").lower() in ("true", "1", "yes"):
        return None, head, "build_all requested"
    event_name = env.get("GITHUB_EVENT_NAME", "")
    ref = env.get("GITHUB_REF", "")
    event: dict = {}
    path = env.get("GITHUB_EVENT_PATH")
    if path and os.path.isfile(path):
        try:
            with open(path) as f:
                event = json.load(f)
        except (OSError, ValueError):
            event = {}

    if ref.startswith("refs/tags/"):
        tag = ref[len("refs/tags/") :]
        prefix = tag[0] if tag[:1].isalpha() else ""
        prev = _git(repo_root, "describe", "--tags", "--abbrev=0", f"--match={prefix}*", f"{head}^")
        if prev and prev.strip():
            prev = prev.strip()
            sha = (_git(repo_root, "rev-list", "-n1", prev) or "").strip()
            if sha:
                return sha, head, f"tag {tag}: changes since {prev}"
        return None, head, f"tag {tag}: no previous tag found"

    if event_name in ("pull_request", "pull_request_target"):
        base = ((event.get("pull_request") or {}).get("base") or {}).get("sha", "")
        if base and _has_commit(repo_root, base):
            mb = (_git(repo_root, "merge-base", base, head) or "").strip()
            if mb:
                return mb, head, f"pull request: changes since merge base {mb[:8]}"
        return None, head, "pull request: base not readable"

    if event_name == "push":
        before = event.get("before", "")
        if not before or before == ZERO_SHA:
            return None, head, "push: new branch"
        if _has_commit(repo_root, before):
            return before, head, f"push: changes since {before[:8]}"
        return None, head, "push: previous head not readable"

    return None, head, f"{event_name or 'local run'}: no range, everything builds"


def changed_files(repo_root: str, base: str, head: str) -> list[str] | None:
    out = _git(repo_root, "diff", "--name-only", "--no-renames", base, head)
    if out is None:
        return None
    return [line for line in out.splitlines() if line]


def file_at(repo_root: str, rev: str, path: str) -> str | None:
    return _git(repo_root, "show", f"{rev}:{path}")


# ----------------------------------------------------------------------------------------------------- paths


def _norm(p: str) -> str:
    p = os.path.normpath(p).replace(os.sep, "/")
    return "" if p == "." else p


def matches(path: str, pattern: str) -> bool:
    """A file path against a glob (`**` crosses directories) or a directory (everything under it)."""
    pattern = _norm(pattern)
    if pattern == "":
        return True
    if any(ch in pattern for ch in "*?["):
        if fnmatch.fnmatchcase(path, pattern):
            return True
        return pattern.endswith("/**") and (path == pattern[:-3] or path.startswith(pattern[:-3] + "/"))
    return path == pattern or path.startswith(pattern + "/")


# ----------------------------------------------------------------------------------------------------- cargo


def workspace_packages(ws_dir_abs: str, repo_root: str) -> dict[str, str]:
    """Workspace package name -> its directory, relative to the repo root."""
    out: dict[str, str] = {}
    try:
        with open(os.path.join(ws_dir_abs, "Cargo.toml"), "rb") as f:
            ws = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return out
    members = ((ws.get("workspace") or {}).get("members")) or []
    dirs: list[str] = []
    for m in members:
        dirs.extend(sorted(glob.glob(os.path.join(ws_dir_abs, m))))
    if "package" in ws:
        dirs.append(ws_dir_abs)
    for d in dirs:
        try:
            with open(os.path.join(d, "Cargo.toml"), "rb") as f:
                name = (tomllib.load(f).get("package") or {}).get("name")
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if name:
            out[name] = _norm(os.path.relpath(d, repo_root))
    return out


def _lock_packages(lock_text: str | None) -> list[dict]:
    if not lock_text:
        return []
    try:
        return tomllib.loads(lock_text).get("package") or []
    except tomllib.TOMLDecodeError:
        return []


def lock_closure(lock_text: str | None, roots: list[str]) -> tuple[set[str], set[tuple[str, str, str]]]:
    """(workspace/path package names, external (name, version, source)) reachable from roots in a Cargo.lock."""
    pkgs = _lock_packages(lock_text)
    by_name: dict[str, list[dict]] = {}
    for p in pkgs:
        by_name.setdefault(p.get("name", ""), []).append(p)

    def resolve(dep: str) -> dict | None:
        parts = dep.split(" ")
        cands = by_name.get(parts[0], [])
        if len(parts) >= 2:
            cands = [c for c in cands if c.get("version") == parts[1]]
        if len(parts) >= 3:
            src = parts[2].strip("()")
            cands = [c for c in cands if (c.get("source") or "") == src]
        return cands[0] if len(cands) == 1 else (cands[0] if cands else None)

    local: set[str] = set()
    external: set[tuple[str, str, str]] = set()
    seen: set[tuple[str, str, str]] = set()
    stack = [c for r in roots for c in by_name.get(r, []) if not c.get("source")]
    while stack:
        p = stack.pop()
        key = (p.get("name", ""), p.get("version", ""), p.get("source") or "")
        if key in seen:
            continue
        seen.add(key)
        if key[2]:
            external.add(key)
        else:
            local.add(key[0])
        for d in p.get("dependencies") or []:
            q = resolve(d)
            if q is not None:
                stack.append(q)
    return local, external


# ----------------------------------------------------------------------------------------------------- artifacts


def _env(artifact: dict) -> dict[str, str]:
    env = (artifact.get("buildpacks") or {}).get("env")
    out: dict[str, str] = {}
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    for e in env if isinstance(env, list) else (env.split() if isinstance(env, str) else []):
        if isinstance(e, str) and "=" in e:
            k, v = e.split("=", 1)
            out[k] = v
    return out


def artifact_change(
    artifact: dict, repo_root: str, files: list[str], base: str, head: str, cache: dict
) -> tuple[bool, str]:
    """(changed, why) for one skaffold artifact over the changed files of base..head."""
    context = _norm(artifact.get("context", "."))
    env = _env(artifact)
    deps = (artifact.get("buildpacks") or {}).get("dependencies") or {}
    extra = [_norm(os.path.join(context, p)) for p in deps.get("paths") or []]
    ignore = [_norm(os.path.join(context, p)) for p in deps.get("ignore") or []]
    considered = [f for f in files if not any(matches(f, i) for i in ignore)]

    inputs: list[str] = []
    suite_map = env.get("BP_SUITE_IMAGES", "").strip()
    if suite_map:
        inputs.append(_norm(os.path.join(context, suite_map)))
    packages = [p.strip() for p in env.get("BP_RUST_PACKAGES", "").split(",") if p.strip()]
    ws_rel = _norm(os.path.join(context, env.get("BP_RUST_WORKSPACE_DIR", ".") or "."))
    rust = os.path.isfile(os.path.join(repo_root, ws_rel, "Cargo.toml"))
    if rust and packages:
        lock_rel = _norm(os.path.join(ws_rel, "Cargo.lock"))
        key = ("ws", ws_rel)
        if key not in cache:
            cache[key] = (
                workspace_packages(os.path.join(repo_root, ws_rel), repo_root),
                file_at(repo_root, head, lock_rel),
                file_at(repo_root, base, lock_rel),
            )
        members, lock_head, lock_base = cache[key]
        local, ext_head = lock_closure(lock_head, packages)
        local |= set(packages)
        inputs += [members[p] for p in sorted(local) if p in members]
        inputs += [
            _norm(os.path.join(ws_rel, "Cargo.toml")),
            _norm(os.path.join(ws_rel, "rust-toolchain")),
            _norm(os.path.join(ws_rel, "rust-toolchain.toml")),
        ]
        if lock_rel in considered:
            if lock_base is None:
                return True, f"{lock_rel} is new"
            _, ext_base = lock_closure(lock_base, packages)
            if ext_head != ext_base:
                diff = sorted({n for n, _, _ in ext_head ^ ext_base})
                return True, f"{lock_rel}: {', '.join(diff[:5])}{' …' if len(diff) > 5 else ''} changed"
    else:
        inputs.append(context)
    inputs += extra

    hits = [f for f in considered if any(matches(f, i) for i in inputs)]
    if hits:
        return True, f"{hits[0]}{f' and {len(hits) - 1} more' if len(hits) > 1 else ''}"
    return False, "no change to its inputs"


def chart_change(path: str, files: list[str]) -> tuple[bool, str]:
    hits = [f for f in files if matches(f, path)]
    if hits:
        return True, f"{hits[0]}{f' and {len(hits) - 1} more' if len(hits) > 1 else ''}"
    return False, "no change to the chart"


# ----------------------------------------------------------------------------------------------------- filtering


def filter_context(ctx: dict, artifacts: list[dict], repo_root: str, skaffold_rel: str, env: dict[str, str]) -> dict:
    """Drop the legs whose artifacts did not change; record what ran, what was skipped and why."""
    base, head, why_range = commit_range(repo_root, env)
    summary: dict = {"active": True, "range": why_range, "changed": {}, "skipped": {}}
    ctx["change_detection"] = summary
    if base is None:
        summary["changed"] = {a.get("image", ""): "everything builds" for a in artifacts if a.get("image")}
        return ctx
    files = changed_files(repo_root, base, head)
    if files is None:
        summary["range"] += "; diff unreadable, everything builds"
        return ctx
    summary["files"] = len(files)

    always = [p.strip() for p in env.get("ALWAYS_REBUILD_PATHS", "").replace("\n", ",").split(",") if p.strip()]
    global_hits = [f for f in files if any(matches(f, g) for g in (skaffold_rel, *GLOBAL_PATTERNS, *always))]
    if global_hits:
        summary["range"] += f"; {global_hits[0]} changed, everything builds"
        summary["changed"] = {a.get("image", ""): "global input" for a in artifacts if a.get("image")}
        return ctx

    cache: dict = {}
    changed: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for a in artifacts:
        image = a.get("image", "")
        if not image:
            continue
        hit, why = artifact_change(a, repo_root, files, base, head, cache)
        (changed if hit else skipped)[image] = why
    chart_paths = ctx.get("chart_paths") or []
    chart_changed: dict[str, bool] = {}
    for p in chart_paths:
        hit, why = chart_change(p, files)
        chart_changed[p] = hit
        (changed if hit else skipped)[f"chart:{p}"] = why

    # Waves: a dependent rebuilds with its dependency, and a dependency builds when its dependent does (wave 1
    # takes wave 0's build results).
    integ = ctx.get("integration_matrix") or []
    by_key = {e.get("output_key"): e for e in integ}
    moved = True
    while moved:
        moved = False
        for e in integ:
            img = e.get("image", "")
            for d in e.get("depends_on") or []:
                dep = by_key.get(d, {}).get("image", "")
                if dep in changed and img in skipped:
                    changed[img] = f"depends on {dep}"
                    skipped.pop(img)
                    moved = True
                if img in changed and dep in skipped:
                    changed[dep] = f"{img} depends on it"
                    skipped.pop(dep)
                    moved = True

    def keep_integration(e: dict) -> bool:
        if e.get("type") == "chart":
            return chart_changed.get(e.get("path", ""), True)
        return e.get("image", "") not in skipped

    def keep_matrix(e: dict) -> bool:
        if e.get("language") == "helm":
            return chart_changed.get(e.get("context", ""), True)
        covered = e.get("artifacts") or ([e.get("name")] if e.get("name") else [])
        return any(c not in skipped for c in covered) if covered else True

    ctx["integration_matrix"] = [e for e in integ if keep_integration(e)]
    ctx["integration_matrix_wave0"] = [e for e in ctx["integration_matrix"] if e.get("wave", 0) == 0]
    ctx["integration_matrix_wave1"] = [e for e in ctx["integration_matrix"] if e.get("wave", 0) == 1]
    ctx["matrix"] = [e for e in ctx.get("matrix", []) if keep_matrix(e)]
    ctx["deliverables_matrix"] = [e for e in ctx.get("deliverables_matrix", []) if e.get("image", "") not in skipped]
    summary["changed"] = changed
    summary["skipped"] = skipped
    return ctx


def write_summary(ctx: dict, path: str | None) -> None:
    s = ctx.get("change_detection")
    if not s:
        return
    lines = ["### Change detection", "", s.get("range", ""), "", "| Artifact | Builds | Why |", "| --- | --- | --- |"]
    for img, why in sorted((s.get("changed") or {}).items()):
        lines.append(f"| `{img}` | yes | {why} |")
    for img, why in sorted((s.get("skipped") or {}).items()):
        lines.append(f"| `{img}` | skipped | {why} |")
    text = "\n".join(lines) + "\n"
    sys.stderr.write(text)
    if path:
        with open(path, "a") as f:
            f.write(text)
