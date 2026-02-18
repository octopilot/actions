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
    # Check pom.xml or build.gradle
    content = get_file_content(context, "pom.xml")
    if content:
        # Simple regex for parsing xml
        match = re.search(r"<java.version>(.*?)</java.version>", content)
        if match:
            return match.group(1)
        match = re.search(r"<maven.compiler.source>(.*?)</maven.compiler.source>", content)
        if match:
            return match.group(1)

    content = get_file_content(context, "build.gradle")
    if content:
        match = re.search(r"sourceCompatibility\s*=\s*['\"](.*?)['\"]", content)
        if match:
            return match.group(1)

    return ""


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


def main():
    skaffold_file = os.environ.get("SKAFFOLD_FILE", "skaffold.yaml")

    if not os.path.exists(skaffold_file):
        sys.stderr.write(f"Error: {skaffold_file} not found.\n")
        # Output empty matrix to avoid workflow failure
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("matrix=[]\n")
                f.write("languages=\n")
        else:
            print("matrix=[]")  # noqa: T201
            print("languages=")  # noqa: T201
        return

    try:
        with open(skaffold_file) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        sys.stderr.write(f"Error parsing {skaffold_file}: {e}\n")
        sys.exit(1)

    artifacts = config.get("build", {}).get("artifacts", [])
    matrix_include = []

    for artifact in artifacts:
        image = artifact.get("image")
        context = artifact.get("context", ".")

        info = detect_project_info(context)

        if info:
            language = info["language"]
            version = info["version"]
            sys.stderr.write(f"Detected {language} ({version}) for {image} in {context}\n")
            matrix_include.append({"name": image, "context": context, "language": language, "version": version})
        else:
            sys.stderr.write(f"Could not detect language for {image} in {context}\n")

    # Output JSON for GitHub Actions Matrix
    json_output = json.dumps(matrix_include)

    # Output unique languages for lint workflow (comma-separated)
    # Fix C414/C401: Unnecessary list call within sorted(), set comprehension
    unique_langs_set: set[str] = set()
    for item in matrix_include:
        lang = item.get("language")
        if isinstance(lang, str) and lang:
            unique_langs_set.add(lang)

    unique_langs = sorted(unique_langs_set)
    langs_output = ",".join(unique_langs)

    # Aggregate versions for repository-wide tools (e.g., lint)
    # We pick the "latest" version string found for each language as a heuristic
    versions = {}
    for lang in unique_langs:
        # Collect all versions for this language
        langs_versions = {item["version"] for item in matrix_include if item["language"] == lang and item["version"]}
        if langs_versions:
            # Simple string sort for now (sufficient for standard semver like 1.21 < 1.22)
            # For complex constraints (>=18), this might just pick one.
            best_version = sorted(langs_versions)[-1]
            versions[lang] = best_version

    # Create consolidated pipeline context
    pipeline_context = {"matrix": matrix_include, "languages": unique_langs, "versions": versions}

    # Also add individual version keys for convenience if needed,
    # but the primary goal is to pass `pipeline_context` as a single object.
    # For backward compatibility or ease of use, we keep the exploded outputs too.

    pipeline_context_json = json.dumps(pipeline_context)

    # GitHub Actions Output Format
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
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


if __name__ == "__main__":
    main()
