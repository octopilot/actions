import json
import os
import sys

import yaml


def detect_language(context_path):
    """Detects language based on files in the context directory."""
    if not os.path.exists(context_path):
        return None

    try:
        files = os.listdir(context_path)
    except OSError:
        return None

    if "go.mod" in files:
        return "go"
    if "Cargo.toml" in files:
        return "rust"
    if "package.json" in files:
        return "node"
    if "requirements.txt" in files or "pyproject.toml" in files or "Pipfile" in files:
        return "python"
    if "pom.xml" in files or "build.gradle" in files or "build.gradle.kts" in files:
        return "java"

    return None


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

        language = detect_language(context)

        if language:
            sys.stderr.write(f"Detected {language} for {image} in {context}\n")
            matrix_include.append({"name": image, "context": context, "language": language})
        else:
            sys.stderr.write(f"Could not detect language for {image} in {context}\n")

    # Output JSON for GitHub Actions Matrix
    json_output = json.dumps(matrix_include)

    # Output unique languages for lint workflow (comma-separated)
    # Fix C414/C401: Unnecessary list call within sorted(), set comprehension
    unique_langs = sorted({item["language"] for item in matrix_include})
    langs_output = ",".join(unique_langs)

    # GitHub Actions Output Format
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"matrix={json_output}\n")
            f.write(f"languages={langs_output}\n")
    else:
        print(f"matrix={json_output}")  # noqa: T201
        print(f"languages={langs_output}")  # noqa: T201


if __name__ == "__main__":
    main()
