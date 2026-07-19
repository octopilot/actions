import json
import os
import re
import sys
import tomllib  # Requires Python 3.11+

import yaml


def get_file_content(context_path: str, filename: str) -> str | None:
    try:
        with open(os.path.join(context_path, filename)) as f:
            return f.read()
    except OSError:
        return None


def detect_go_version(context: str) -> str:
    content = get_file_content(context, "go.mod")
    if content:
        match = re.search(r"^go\s+(\S+)", content, re.MULTILINE)
        if match:
            return match.group(1)
    return ""


def detect_rust_version(context: str) -> str:
    # Check rust-toolchain channel (e.g., stable, nightly, 1.70.0)
    for f in ["rust-toolchain", "rust-toolchain.toml"]:
        content = get_file_content(context, f)
        if content:
            if f.endswith(".toml"):
                try:
                    data = tomllib.loads(content)
                    return data.get("toolchain", {}).get("channel", "")
                except Exception as e:
                    sys.stderr.write(f"Error parsing {f}: {e}\n")
            return content.strip()
    return ""


def detect_node_version(context: str) -> str:
    # Check package.json engines or .nvmrc
    content = get_file_content(context, "package.json")
    if content:
        try:
            data = json.loads(content)
            version = data.get("engines", {}).get("node", "")
            if version:
                return version
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Error parsing package.json: {e}\n")

    content = get_file_content(context, ".nvmrc")
    if content:
        return content.strip()
    return ""


def detect_python_version(context: str) -> str:
    # Check pyproject.toml requires-python or .python-version
    content = get_file_content(context, "pyproject.toml")
    if content:
        try:
            data = tomllib.loads(content)
            version = data.get("project", {}).get("requires-python", "")
            if version:
                return version
        except Exception as e:
            sys.stderr.write(f"Error parsing pyproject.toml: {e}\n")

    content = get_file_content(context, ".python-version")
    if content:
        return content.strip()
    return ""


def detect_java_version(context: str) -> str:
    # Maven: pom.xml
    content = get_file_content(context, "pom.xml")
    if content:
        match = re.search(r"<java\.version>(.*?)</java\.version>", content)
        if match:
            return match.group(1).strip()
        match = re.search(r"<maven\.compiler\.source>(.*?)</maven\.compiler\.source>", content)
        if match:
            return match.group(1).strip()
        match = re.search(r"<maven\.compiler\.(?:source|target)>(.*?)</maven\.compiler\.(?:source|target)>", content)
        if match:
            return match.group(1).strip()

    # Gradle (Groovy): build.gradle
    content = get_file_content(context, "build.gradle")
    if content:
        match = re.search(r"sourceCompatibility\s*=\s*['\"]?(?:JavaVersion\.)?VERSION_(\d+)['\"]?", content)
        if match:
            return match.group(1)
        match = re.search(r"sourceCompatibility\s*=\s*['\"](\d+)['\"]", content)
        if match:
            return match.group(1)

    # Gradle (Kotlin DSL): build.gradle.kts — JavaLanguageVersion.of(17) or jvmTarget = "17"
    content = get_file_content(context, "build.gradle.kts")
    if content:
        match = re.search(r"JavaLanguageVersion\.of\((\d+)\)", content)
        if match:
            return match.group(1)
        match = re.search(r"languageVersion\.set\s*\(\s*JavaLanguageVersion\.of\((\d+)\)", content)
        if match:
            return match.group(1)
        match = re.search(r'jvmTarget\s*=\s*["\'](\d+)["\']', content)
        if match:
            return match.group(1)
        # Gradle Kotlin DSL: JvmTarget.JVM_17
        match = re.search(r"JvmTarget\.JVM_(\d+)", content)
        if match:
            return match.group(1)

    return ""


def _java_version_to_bp_jvm(version: str) -> str:
    """Normalize Java version to a major number for BP_JVM_VERSION (e.g. 1.8 -> 8, 17 -> 17)."""
    if not version:
        return ""
    version = version.strip()
    if version.startswith("1.") and len(version) > 2:
        return version[2:].split(".")[0] or version
    return version.split(".")[0]


def _gradle_bp_env_from_context(context_abs: str) -> dict[str, str]:
    """
    Extract Paketo/Java Gradle buildpack env vars from a Java/Gradle project directory.
    Only sets vars we can derive from the repo; skaffold buildpacks.env can override.
    Paketo Gradle buildpack variables (we set BP_JVM_VERSION, BP_GRADLE_BUILD_FILE when derivable):
      BP_EXCLUDE_FILES          colon-separated globs, matched source files removed
      BP_GRADLE_ADDITIONAL_BUILD_ARGUMENTS  appended to BP_GRADLE_BUILD_ARGUMENTS
      BP_GRADLE_BUILD_ARGUMENTS default: --no-daemon -Dorg.gradle.welcome=never assemble
      BP_GRADLE_BUILD_FILE      main build config file (we set from presence of build.gradle.kts / build.gradle)
      BP_GRADLE_BUILT_ARTIFACT  default: build/libs/*.[jw]ar
      BP_GRADLE_BUILT_MODULE    module to find application artifact in
      BP_GRADLE_INIT_SCRIPT_PATH  path to Gradle init script
      BP_INCLUDE_FILES          colon-separated globs, matched source files included
      BP_JAVA_INSTALL_NODE      default: false (Yarn/Node from package.json / yarn.lock)
      BP_JVM_VERSION            Java major version (we set from Gradle/pom.xml)
    """
    out: dict[str, str] = {}
    info = detect_project_info(context_abs)
    if not info or info.get("language") != "java":
        return out
    version = info.get("version")
    if version:
        bp_jvm = _java_version_to_bp_jvm(str(version))
        if bp_jvm:
            out["BP_JVM_VERSION"] = bp_jvm
    if os.path.isfile(os.path.join(context_abs, "build.gradle.kts")):
        out["BP_GRADLE_BUILD_FILE"] = "build.gradle.kts"
    elif os.path.isfile(os.path.join(context_abs, "build.gradle")):
        out["BP_GRADLE_BUILD_FILE"] = "build.gradle"
    return out


def detect_helm_charts(repo_root: str) -> list[str]:
    """Find all directories that contain a Chart.yaml (Helm chart)."""
    chart_paths: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(repo_root):
        if "Chart.yaml" in filenames:
            rel = os.path.relpath(dirpath, repo_root)
            if not rel.startswith(".git"):
                chart_paths.append(rel if rel != "." else ".")
        # Skip .git and other hidden dirs to avoid unnecessary walk
        _dirnames[:] = [d for d in _dirnames if not d.startswith(".")]
    return sorted(chart_paths)


def detect_project_info(context_path: str) -> dict[str, str | None] | None:
    """Detects language and version based on files in the context directory."""
    if not os.path.exists(context_path):
        return None

    try:
        files = os.listdir(context_path)
    except OSError:
        return None

    info = {"language": None, "version": ""}

    if "go.mod" in files:
        info["language"] = "go"
        info["version"] = detect_go_version(context_path)
    elif "Cargo.toml" in files:
        info["language"] = "rust"
        info["version"] = detect_rust_version(context_path)
    elif "package.json" in files:
        info["language"] = "node"
        info["version"] = detect_node_version(context_path)
    elif "requirements.txt" in files or "pyproject.toml" in files or "Pipfile" in files:
        info["language"] = "python"
        info["version"] = detect_python_version(context_path)
    elif "pom.xml" in files or "build.gradle" in files or "build.gradle.kts" in files:
        info["language"] = "java"
        info["version"] = detect_java_version(context_path)
    else:
        return None

    return info


# ── Meta-build functions ─────────────────────────────────────────────────────
# skaffold build.artifacts entries are named OCI artifacts, not necessarily
# images. Reserved image-name suffixes route an artifact to a non-image
# meta-build function (the `-chart` precedent, handled by op itself):
#   -lib  → lib     "build and test it all" for the declared context; the
#                    deliverable is a verified rev (publish optional via
#                    BP_LIB_PUBLISH=crates-io|pypi|github-release|none)
#   -bin  → binary  release binaries (BP_BIN_PACKAGES), GH release on tags
# Everything else (incl. -chart) stays an integration-matrix entry.
RESERVED_DELIVERABLE_SUFFIXES = {"lib": "lib", "bin": "binary"}


def artifact_env(artifact: dict) -> dict[str, str]:
    """Parse an artifact's buildpacks.env (list/dict/str) into a dict."""
    env = (artifact.get("buildpacks") or {}).get("env")
    out: dict[str, str] = {}
    if isinstance(env, dict):
        out = {str(k): str(v) for k, v in env.items()}
    elif isinstance(env, list):
        for e in env:
            if isinstance(e, str) and "=" in e:
                k, v = e.split("=", 1)
                out[k] = v
    elif isinstance(env, str):
        for e in env.split():
            if "=" in e:
                k, v = e.split("=", 1)
                out[k] = v
    return out


def artifact_function(artifact: dict) -> str:
    """Resolve the meta-build function for an artifact from its reserved image-name suffix."""
    image = artifact.get("image", "") or ""
    image_name = image.split("/")[-1].split(":")[0]
    suffix = image_name.rsplit("-", 1)[-1] if "-" in image_name else ""
    return RESERVED_DELIVERABLE_SUFFIXES.get(suffix, "image")


def effective_context(context_abs: str, env: dict[str, str]) -> str:
    """Directory whose marker files define the language — honors BP_RUST_WORKSPACE_DIR
    (nested Cargo workspaces, e.g. a repo whose workspace root is `microservices/`)."""
    ws = env.get("BP_RUST_WORKSPACE_DIR", "").strip()
    if ws and ws != ".":
        return os.path.normpath(os.path.join(context_abs, ws))
    return context_abs


def synthesize_rust_test_command(context_dir: str) -> str | None:
    """Archetype inference: some rust projects need more than a bare `cargo test`.

    A BRRTRouter-based context (the BRRTRouter repo itself, or a service that
    depends on it) is detected from its Cargo.toml, and the test ritual is
    synthesized from cheap, observable signals:
      * test sources referencing a musl target  -> provision musl toolchain
        (BRRTRouter e2e harnesses cross-build the service and run it on Alpine)
      * committed .cargo/config.toml rustflags  -> neutralize RUSTFLAGS
        (parity with repos whose own CI overrides the config)
      * brrtrouter-gen + examples/openapi.yaml  -> regenerate handlers pre-test
    An explicitly declared BP_TEST_COMMAND always wins over this inference.
    Returns None for non-BRRTRouter contexts (the test action's default runs).
    """
    cargo_content = get_file_content(context_dir, "Cargo.toml")
    if not cargo_content:
        return None
    try:
        cargo = tomllib.loads(cargo_content)
    except Exception as e:
        sys.stderr.write(f"Error parsing Cargo.toml in {context_dir}: {e}\n")
        return None

    pkg_name = cargo.get("package", {}).get("name", "")
    bins = cargo.get("bin", []) or []
    deps = dict(cargo.get("dependencies", {}) or {})
    deps.update(cargo.get("workspace", {}).get("dependencies", {}) or {})
    is_brrt_repo = pkg_name == "brrtrouter" or any(
        isinstance(b, dict) and b.get("name") == "brrtrouter-gen" for b in bins
    )
    uses_brrt = "brrtrouter" in deps
    if not (is_brrt_repo or uses_brrt):
        return None

    # Structural variant: workspace members in gen/impl pairs + an openapi/
    # spec tree = a generated BRRTRouter microservice (gen crates committed;
    # CI compiles them as-is and never regenerates — regen is a dev-time step).
    members = cargo.get("workspace", {}).get("members", []) or []
    has_gen_impl_pairs = any(str(m).endswith("/gen") for m in members) and any(
        str(m).endswith("/impl") for m in members
    )
    is_brrt_service = uses_brrt and (
        has_gen_impl_pairs or os.path.isdir(os.path.join(context_dir, "openapi"))
    )
    archetype = "brrtrouter-repo" if is_brrt_repo else (
        "brrtrouter-service" if is_brrt_service else "brrtrouter-consumer"
    )
    sys.stderr.write(f"Rust archetype detected in {context_dir}: {archetype}\n")

    parts: list[str] = []

    # musl e2e harness: any test source referencing a musl target triple
    musl = False
    tests_dir = os.path.join(context_dir, "tests")
    if os.path.isdir(tests_dir):
        try:
            for fn in sorted(os.listdir(tests_dir)):
                if not fn.endswith(".rs"):
                    continue
                content = get_file_content(tests_dir, fn)
                if content and "unknown-linux-musl" in content:
                    musl = True
                    break
        except OSError:
            pass
    if musl:
        parts.append("sudo apt-get update -qq && sudo apt-get install -y -qq musl-tools")
        parts.append("rustup target add x86_64-unknown-linux-musl")

    exports: list[str] = []
    cargo_cfg = get_file_content(context_dir, os.path.join(".cargo", "config.toml"))
    if cargo_cfg and "rustflags" in cargo_cfg:
        exports.append("RUSTFLAGS=")
    if musl:
        exports.append("CC_x86_64_unknown_linux_musl=musl-gcc")
        exports.append("CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc")
    if exports:
        parts.append("export " + " ".join(exports))

    # Spec-driven codegen: the BRRTRouter repo regenerates its example service
    # from the OpenAPI spec before testing (generated code must match the spec).
    if is_brrt_repo and os.path.isfile(os.path.join(context_dir, "examples", "openapi.yaml")):
        parts.append("cargo run --bin brrtrouter-gen -- generate --spec examples/openapi.yaml --force")

    parts.append(
        'cargo llvm-cov test --workspace --all-targets --no-fail-fast '
        '--lcov --output-path "$GITHUB_WORKSPACE/coverage/lcov.info"'
    )
    return " && ".join(parts)


def build_matrix_include(artifacts: list[dict], repo_root: str) -> list[dict]:
    """Build the test/lint matrix from skaffold artifacts (language detection per context).

    Entries are deduped on (language, effective context dir): N artifacts selecting
    packages out of one workspace (BP_RUST_PACKAGE=...) yield one lint/test entry,
    not N identical ones.
    """
    matrix_include: list[dict] = []
    entry_by_key: dict[tuple[str, str], dict] = {}
    for artifact in artifacts:
        image = artifact.get("image")
        context = artifact.get("context", ".")
        env = artifact_env(artifact)
        context_abs = os.path.normpath(os.path.join(repo_root, context))
        probe_dir = effective_context(context_abs, env)
        info = detect_project_info(probe_dir)
        if info:
            language = info["language"]
            version = info["version"] or ""
            key = (str(language), probe_dir)
            entry = entry_by_key.get(key)
            if entry is None:
                sys.stderr.write(f"Detected {language} ({version}) for {image} in {context}\n")
                entry = {"name": image, "context": context, "language": language, "version": version}
                entry_by_key[key] = entry
                matrix_include.append(entry)
            else:
                sys.stderr.write(f"Deduped {language} context for {image} ({probe_dir} already covered)\n")
            # A context's test command may be declared (BP_TEST_COMMAND) on ANY
            # artifact sharing that context — -lib artifacts are the natural
            # home. The test action honors matrix.command over its default.
            if env.get("BP_TEST_COMMAND") and not entry.get("command"):
                entry["command"] = env["BP_TEST_COMMAND"]
                sys.stderr.write(f"Test command override for {entry['name']}: {entry['command']}\n")
        else:
            sys.stderr.write(f"Could not detect language for {image} in {context}\n")

    # Archetype inference (declared BP_TEST_COMMAND always wins): rust contexts
    # without a declared command may still need more than a bare `cargo test` —
    # synthesize the ritual from observable signals (see synthesize_rust_test_command).
    for key, entry in entry_by_key.items():
        if entry.get("language") == "rust" and not entry.get("command"):
            synthesized = synthesize_rust_test_command(key[1])
            if synthesized:
                entry["command"] = synthesized
                sys.stderr.write(f"Synthesized test command for {entry['name']}: {synthesized}\n")
    return matrix_include


def build_integration_matrix(artifacts: list[dict], chart_paths: list[str], repo_root: str) -> list[dict]:
    """Build integration matrix (image docker/pack + chart entries) from skaffold artifacts and chart_paths."""
    integration_matrix: list[dict] = []
    for artifact in artifacts:
        image = artifact.get("image", "")
        context = artifact.get("context", ".")
        if not image:
            continue
        # Non-image meta-build functions (-lib, -bin) are verified in the
        # deliverables matrix — never pack/docker-built as images.
        if artifact_function(artifact) != "image":
            continue
        image_name = image.split("/")[-1].split(":")[0]
        parts = image_name.split("-")
        suffix = parts[-1] if parts else image_name
        output_key = f"image_{suffix}"
        context_abs = os.path.normpath(os.path.join(repo_root, context))
        has_dockerfile = os.path.isfile(os.path.join(context_abs, "Dockerfile"))
        build_method = "docker" if has_dockerfile else "pack"
        entry: dict = {
            "type": "image",
            "image": image,
            "build_method": build_method,
            "context": context,
            "suffix": suffix,
            "output_key": output_key,
        }
        if build_method == "docker":
            entry["dockerfile"] = "Dockerfile"
        if build_method == "pack":
            buildpacks = artifact.get("buildpacks") or {}
            entry["builder"] = buildpacks.get("builder", "paketobuildpacks/builder-jammy-base")
            env = buildpacks.get("env")
            if isinstance(env, dict):
                entry["build_env"] = " ".join(f"{k}={v}" for k, v in env.items())
            elif isinstance(env, str):
                entry["build_env"] = env
            elif isinstance(env, list):
                entry["build_env"] = " ".join(str(e) for e in env)
            bp_extra = _gradle_bp_env_from_context(context_abs)
            if bp_extra:
                existing = entry.get("build_env") or ""
                existing_keys = {p.split("=", 1)[0] for p in existing.split() if "=" in p}
                extra_parts = [f"{k}={v}" for k, v in bp_extra.items() if k not in existing_keys]
                if extra_parts:
                    entry["build_env"] = f"{existing} {' '.join(extra_parts)}".strip()
        integration_matrix.append(entry)
    # Contexts already built as images (e.g. pack with helm buildpack) — skip duplicate chart entry
    artifact_contexts = {os.path.normpath(e["context"]) for e in integration_matrix}
    for path in chart_paths:
        path_norm = os.path.normpath(path)
        if path_norm in artifact_contexts:
            continue
        integration_matrix.append({"type": "chart", "path": path, "output_key": "chart", "image": ""})
    return integration_matrix


def build_deliverables_matrix(artifacts: list[dict], repo_root: str) -> list[dict]:
    """Build the deliverables matrix: non-image meta-build functions (lib, binary).

    A `lib` deliverable's every-run phase is "build and test it all" for its context;
    with publish mode `none` (default) the deliverable is the verified rev itself
    (git-consumed library model). `binary` covers release binaries.
    """
    deliverables: list[dict] = []
    for artifact in artifacts:
        function = artifact_function(artifact)
        if function == "image":
            continue
        image = artifact.get("image", "")
        context = artifact.get("context", ".")
        env = artifact_env(artifact)
        context_abs = os.path.normpath(os.path.join(repo_root, context))
        probe_dir = effective_context(context_abs, env)
        info = detect_project_info(probe_dir) or {"language": None, "version": ""}
        image_name = image.split("/")[-1].split(":")[0]
        base = image_name.rsplit("-", 1)[0] or image_name
        short = base.split("-")[-1]
        if function == "lib":
            publish = env.get("BP_LIB_PUBLISH", "none")
        else:
            publish = "github-release"
        entry: dict = {
            "type": function,
            "image": image,
            "context": context,
            "language": info["language"] or "",
            "version": info["version"] or "",
            "output_key": f"{function}_{short}",
            "publish": publish,
        }
        # BP_TEST_COMMAND (may contain spaces) belongs to the lint/test matrix,
        # not the deliverable's space-joined build_env.
        env_out = {k: v for k, v in env.items() if k != "BP_TEST_COMMAND"}
        if env_out:
            entry["build_env"] = " ".join(f"{k}={v}" for k, v in env_out.items())
        sys.stderr.write(
            f"Deliverable {function} ({entry['language'] or 'unknown'}) for {image} in {context} (publish={publish})\n"
        )
        deliverables.append(entry)
    return deliverables


def build_pipeline_context(config: dict, repo_root: str) -> dict:
    """
    Build the full pipeline context (matrix, languages, versions, chart_paths, integration_matrix).
    Pure in terms of config; uses filesystem for detect_project_info, detect_helm_charts, and Dockerfile check.
    """
    artifacts = config.get("build", {}).get("artifacts", [])
    matrix_include = build_matrix_include(artifacts, repo_root)
    chart_paths = detect_helm_charts(repo_root)
    for path in chart_paths:
        name = f"helm-{path}" if path != "." else "helm"
        matrix_include.append({"name": name, "context": path, "language": "helm", "version": ""})

    integration_matrix = build_integration_matrix(artifacts, chart_paths, repo_root)
    deliverables_matrix = build_deliverables_matrix(artifacts, repo_root)

    unique_langs_set: set[str] = set()
    for item in matrix_include:
        lang = item.get("language")
        if isinstance(lang, str) and lang:
            unique_langs_set.add(lang)
    if chart_paths:
        unique_langs_set.add("helm")
        for path in chart_paths:
            sys.stderr.write(f"Detected Helm chart: {path}\n")
    unique_langs = sorted(unique_langs_set)

    versions: dict[str, str] = {}
    for lang in unique_langs:
        if lang == "helm":
            versions[lang] = ""
            continue
        langs_versions = {item["version"] for item in matrix_include if item["language"] == lang and item["version"]}
        if langs_versions:
            versions[lang] = sorted(langs_versions)[-1]
        else:
            versions[lang] = ""

    return {
        "matrix": matrix_include,
        "languages": unique_langs,
        "versions": versions,
        "chart_paths": chart_paths,
        "integration_matrix": integration_matrix,
        "deliverables_matrix": deliverables_matrix,
    }


def write_outputs(pipeline_context: dict, github_output_path: str | None = None) -> None:
    """Write matrix, languages, pipeline-context, and lang-version lines to GITHUB_OUTPUT or stdout."""
    matrix = pipeline_context.get("matrix", [])
    languages = pipeline_context.get("languages", [])
    versions = pipeline_context.get("versions", {})
    json_output = json.dumps(matrix)
    langs_output = ",".join(languages)
    pipeline_context_json = json.dumps(pipeline_context)

    if github_output_path:
        with open(github_output_path, "a") as f:
            f.write(f"matrix={json_output}\n")
            f.write(f"languages={langs_output}\n")
            f.write(f"pipeline-context={pipeline_context_json}\n")
            for lang, ver in versions.items():
                f.write(f"{lang}-version={ver}\n")
    else:
        print(f"matrix={json_output}")  # noqa: T201
        print(f"languages={langs_output}")  # noqa: T201
        print(f"pipeline-context={pipeline_context_json}")  # noqa: T201
        for lang, ver in versions.items():
            print(f"{lang}-version={ver}")  # noqa: T201


def main() -> None:
    skaffold_file = os.environ.get("SKAFFOLD_FILE", "skaffold.yaml")

    if not os.path.exists(skaffold_file):
        sys.stderr.write(f"Error: {skaffold_file} not found.\n")
        empty_context = {
            "matrix": [],
            "languages": [],
            "versions": {},
            "chart_paths": [],
            "integration_matrix": [],
            "deliverables_matrix": [],
        }
        write_outputs(empty_context, os.environ.get("GITHUB_OUTPUT"))
        return

    try:
        with open(skaffold_file) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        sys.stderr.write(f"Error parsing {skaffold_file}: {e}\n")
        sys.exit(1)

    repo_root = os.path.dirname(os.path.abspath(skaffold_file))
    pipeline_context = build_pipeline_context(config, repo_root)
    write_outputs(pipeline_context, os.environ.get("GITHUB_OUTPUT"))


if __name__ == "__main__":
    main()
