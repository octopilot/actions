# octopilot-actions

Project-agnostic GitHub Actions for organisations adopting [Octopilot](https://github.com/octopilot). One repository, multiple actions (monorepo).

## Shared code and testing

- **`common/`** — Shared Python package used by actions (e.g. release notes generation). Edit here; actions import from `common`.
- **Tests** — `tests/` contains unit tests (pytest). Run from repo root:
  ```bash
  pip install -e ./common pytest pytest-cov
  PYTHONPATH=common pytest tests/ -v
  ```
- **CI** — `.github/workflows/ci.yml` runs tests and builds the release action Docker image from repo root (so `common/` is included in the image).

## Actions

| Action | Description |
|--------|-------------|
| [**release**](release/README.md) | Generate release notes from commits since last tag using OpenAI or Anthropic; outputs body for GitHub Release. |

## Usage (caller workflow)

Use the **caller pattern**: your repo has a thin workflow that `uses` the reusable workflow from your custom-workflows repo (e.g. `octopilot/sample-custom-workflows`). The reusable workflow can in turn use these actions so you don't need per-repo Python tooling for release notes.

Example step using the release action directly:

```yaml
- name: Generate release notes
  id: notes
  uses: octopilot/actions/release@main
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  with:
    version: ${{ steps.bump.outputs.version }}
    provider: anthropic
    template_path: .github/release-notes-template.md
    output_filename: release-body.md
- name: Create GitHub Release
  uses: softprops/action-gh-release@v2
  with:
    tag_name: "v${{ steps.bump.outputs.version }}"
    body_path: ${{ steps.notes.outputs.body_file }}
    generate_release_notes: false
```

## Design

- **Monolith:** Multiple actions live in this repo under `<name>/`. Each action is self-contained (Docker or composite).
- **Python for v1:** Release notes use Python in a Docker action to reuse battle-tested logic; no per-repo `pip install -e ./tooling` required.
- **Secrets:** Actions document required secrets (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` for release notes).

See [AUDIT-TOOLING-OCTOPILOT-ACTIONS](../octopilot-probot/docs/AUDIT-TOOLING-OCTOPILOT-ACTIONS.md) in octopilot-probot for the audit that led to this layout.
