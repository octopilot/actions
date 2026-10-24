"""Generate release notes from commits since last tag using OpenAI or Anthropic. For GitHub Release body.

The openai provider talks to any OpenAI-compatible endpoint: OPENAI_BASE_URL (default https://api.openai.com/v1) points
it at a self-hosted server such as vLLM, which needs no OPENAI_API_KEY. A reasoning model's <think> block is dropped.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import certifi

DEFAULT_TEMPLATE = """# Release v{{VERSION}}

## Summary
[2-3 sentence overview of this release]

## Changes

### Features
- [List enhancements and new features from commits]

### Fixes
- [List bug fixes from commits]

### Other
- [Docs, chore, refactor, build, ci, etc.]

---
*Generated from commits since the previous release.*"""


class ReleaseNotesError(Exception):
    """Raised when release notes generation fails (no tag, invalid provider, API error, etc.)."""

    pass


def get_previous_tag(project_root: Path) -> str | None:
    """Return the most recent tag that is an ancestor of HEAD, or None if none."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def get_commits_since(project_root: Path, ref: str) -> list[str]:
    """Return list of commit subject lines from ref..HEAD (excluding ref, including HEAD).
    Raises ReleaseNotesError if ref is invalid.
    """
    cmd = ["git", "log", f"{ref}..HEAD", "--pretty=format:%s"]

    # Special case: If ref is v0.0.0 (default fallback) and it doesn't exist, log from start.
    if ref == "v0.0.0":
        try:
            subprocess.run(
                ["git", "rev-parse", "--verify", ref],
                cwd=project_root,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # v0.0.0 does not exist, assume start of history
            cmd = ["git", "log", "HEAD", "--pretty=format:%s"]

    try:
        out = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        hint = f" {e.stderr.strip()}" if (e.stderr and e.stderr.strip()) else ""
        raise ReleaseNotesError(f"Invalid git ref for since_tag: {ref!r}. Check the tag or commit exists.{hint}") from e
    if not out.stdout.strip():
        return []
    return [s for s in out.stdout.strip().split("\n") if s]


def load_template(path: Path | None) -> str:
    """Load template from path or return default."""
    if path is not None and path.is_file():
        return path.read_text()
    return DEFAULT_TEMPLATE


OPENAI_BASE_URL = "https://api.openai.com/v1"


def _openai_base_url() -> str:
    return (os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL).strip().rstrip("/")


def _strip_reasoning(content: str) -> str:
    """Drop a reasoning model's <think>...</think> block (Qwen3 and the like) ahead of the answer."""
    return re.sub(r"^\s*<think>.*?</think>\s*", "", content, flags=re.S)


def _call_openai(commits: list[str], format_instructions: str, version: str, model: str) -> str:
    """Call OpenAI-compatible chat completions (OpenAI, or a self-hosted server: OPENAI_BASE_URL). Returns markdown."""
    base_url = _openai_base_url()
    self_hosted = base_url != OPENAI_BASE_URL
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and not self_hosted:
        raise ReleaseNotesError("OPENAI_API_KEY is not set. Add it as a repository secret for release notes.")

    user_content = (
        f"Follow this format for the release note:\n\n{format_instructions}\n\n"
        f"Version to use in the title: {version}\n\n"
        "Commit messages (one per line):\n" + "\n".join(commits)
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate release notes in Markdown from a list of commit messages. "
                    "Follow the structure provided. Be concise. Use the exact section headers given. "
                    "Do not invent commits; only use the provided list. "
                    "Output only the release note body as Markdown, no extra text or code fences."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
    }
    if self_hosted:
        # vLLM: answer without a thinking phase (Qwen3 chat template); release notes need none.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload["max_tokens"] = 2048

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )

    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(req, timeout=180 if self_hosted else 60, context=ctx) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise ReleaseNotesError(f"OpenAI API error {e.code} ({base_url}): {body}") from e
    except urllib.error.URLError as e:
        raise ReleaseNotesError(f"OpenAI request to {base_url} failed: {e.reason}") from e

    content = _strip_reasoning((data.get("choices") or [{}])[0].get("message", {}).get("content") or "")
    if content.startswith("```"):
        content = re.sub(r"^```(?:markdown)?\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    return content.strip()


def _call_anthropic(commits: list[str], format_instructions: str, version: str, model: str) -> str:
    """Call Anthropic messages API. Returns the generated markdown."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise ReleaseNotesError("ANTHROPIC_API_KEY is not set. Add it as a repository secret for release notes.")

    user_content = (
        f"Follow this format for the release note:\n\n{format_instructions}\n\n"
        f"Version to use in the title: {version}\n\n"
        "Commit messages (one per line):\n" + "\n".join(commits)
    )
    system = (
        "You generate release notes in Markdown from a list of commit messages. "
        "Follow the structure provided. Be concise. Use the exact section headers given. "
        "Do not invent commits; only use the provided list. "
        "Output only the release note body as Markdown, no extra text or code fences."
    )

    payload = {
        "model": model,
        "max_tokens": 2048,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise ReleaseNotesError(f"Anthropic API error {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise ReleaseNotesError(f"Anthropic request failed: {e.reason}") from e

    content = ""
    for block in data.get("content") or []:
        if block.get("type") == "text":
            content = block.get("text") or ""
            break
    if content.startswith("```"):
        content = re.sub(r"^```(?:markdown)?\n?", "", content)
        content = re.sub(r"\n?```\s*$", "", content)
    return content.strip()


def plain_notes(project_root: Path, version: str, since_tag: str | None = None) -> str:
    """Release notes without a model: the commit subjects since the previous tag. The fallback when the provider fails,
    so a release never waits on an AI service."""
    lines = [f"# Release {version}", ""]
    ref = since_tag or get_previous_tag(project_root)
    try:
        commits = get_commits_since(project_root, ref) if ref else []
    except ReleaseNotesError:
        commits = []
    if commits:
        lines += ["## Changes", ""] + [f"- {c}" for c in commits]
        if ref:
            lines += ["", f"*Commits since {ref}.*"]
    return "\n".join(lines)


def run(
    project_root: Path,
    version: str,
    *,
    since_tag: str | None = None,
    template_path: Path | None = None,
    output_path: Path | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """
    Generate release notes: commits since previous tag -> OpenAI or Anthropic -> write to file.
    Returns the body string on success.
    Raises ReleaseNotesError on failure (no previous tag, invalid provider, API error, empty body).
    """
    ref = since_tag or get_previous_tag(project_root)
    if not ref:
        raise ReleaseNotesError("Could not find a previous tag. Use since_tag for the first release.")

    commits = get_commits_since(project_root, ref)
    template = load_template(template_path)
    format_instructions = template.replace("{{VERSION}}", version)

    provider = (provider or os.environ.get("RELEASE_NOTES_PROVIDER") or "anthropic").strip().lower()
    if provider not in ("openai", "anthropic"):
        raise ReleaseNotesError(f"Invalid provider {provider!r}; must be 'openai' or 'anthropic'.")

    if provider == "anthropic":
        model = (model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-5-20250929").strip()
        body = _call_anthropic(commits, format_instructions, version, model)
    else:
        model = (model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
        body = _call_openai(commits, format_instructions, version, model)

    if not (body or "").strip():
        raise ReleaseNotesError("Release notes generation produced empty output.")

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(body, encoding="utf-8")
    return body
