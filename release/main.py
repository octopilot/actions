#!/usr/bin/env python3
"""Entrypoint for release-notes GitHub Action: read INPUT_*, run common.notes.run(), set GITHUB_OUTPUT."""

import os
import sys
from pathlib import Path

from common.notes import ReleaseNotesError
from common.notes import run as run_notes


def _input(name: str) -> str:
    key = f"INPUT_{name.upper().replace('-', '_')}"
    return (os.environ.get(key) or "").strip()


def main() -> None:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if not workspace or not Path(workspace).is_dir():
        print("GITHUB_WORKSPACE is not set or not a directory.", file=sys.stderr)
        sys.exit(1)
    project_root = Path(workspace)

    # Workaround for "dubious ownership" error in GitHub Actions
    import subprocess

    try:
        subprocess.run(["git", "config", "--global", "--add", "safe.directory", "/github/workspace"], check=True)
    except Exception as e:
        print(f"Warning: Failed to set safe.directory: {e}", file=sys.stderr)

    version = _input("version")
    if not version:
        print("Input 'version' is required.", file=sys.stderr)
        sys.exit(1)

    since_tag = _input("since_tag") or None
    template_path = _input("template_path")
    template_inline = _input("template")
    provider = _input("provider") or "anthropic"
    model = _input("model") or None
    output_filename = _input("output_filename") or "release_notes.md"

    template_path_resolved: Path | None = None
    if template_path:
        template_path_resolved = project_root / template_path
    elif template_inline:
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(template_inline)
            template_path_resolved = Path(f.name)

    output_path = project_root / output_filename

    try:
        body = run_notes(
            project_root,
            version,
            since_tag=since_tag,
            template_path=template_path_resolved,
            output_path=output_path,
            model=model,
            provider=provider,
        )
    except ReleaseNotesError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"body_file={output_filename}\n")
            f.write("body<<EOF\n")
            f.write(body)
            f.write("\nEOF\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
