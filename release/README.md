# Release (release notes)

Generates release notes from commits since the previous tag using OpenAI or Anthropic, and writes the result to a file and to action outputs for use with `softprops/action-gh-release` or similar.

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `version` | Yes | - | Release version (e.g. `1.2.3`) |
| `since_tag` | No | previous tag | Git ref (tag or commit) to list commits after |
| `template_path` | No | built-in | Path to Markdown template (relative to repo root). Use `{{VERSION}}` in the template. |
| `template` | No | - | Inline template content (ignored if `template_path` is set) |
| `provider` | No | `anthropic` | AI provider: `openai` or `anthropic` |
| `model` | No | provider default | Model name (e.g. `gpt-4o-mini`, `claude-sonnet-4-5-20250929`) |
| `output_filename` | No | `release_notes.md` | Output file name under repo root |

You can provide your own template in two ways; if you don’t, the built-in default below is used.

- **`template_path`** — Path (relative to repo root) to a Markdown file, e.g. `.github/release-notes-template.md`. Use the placeholder `{{VERSION}}` where the release version should appear.
- **`template`** — Inline template string (same placeholder). Ignored if `template_path` is set.

## Default template

When neither `template_path` nor `template` is set, this template is used. You can copy it to a file (e.g. `.github/release-notes-template.md`), customize it, and pass it via `template_path`.

```markdown
# Release v{{VERSION}}

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
*Generated from commits since the previous release.*
```

## Outputs

| Output | Description |
|--------|-------------|
| `body_file` | Path to the generated file (relative to repo root), e.g. for `body_path` in action-gh-release |
| `body` | Full release notes content |

## Required secrets

- **OpenAI:** `OPENAI_API_KEY` when `provider: openai`
- **Anthropic:** `ANTHROPIC_API_KEY` when `provider: anthropic`

## Example

```yaml
- name: Checkout
  uses: actions/checkout@v4
  with:
    fetch-depth: 0

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

## First release

If there is no previous tag, set `since_tag` to a commit SHA or branch (e.g. `main`):

```yaml
with:
  version: 1.0.0
  since_tag: main
```
