# Previous Tag

Finds the "previous" tag relative to the current commit.
Useful for generating changelogs or release notes.

## Usage

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0 # Required for git describe

- uses: octopilot/actions/previous-tag@main
  id: pre_tag
  with:
    fallback: v0.0.0

- name: Generate Notes
  uses: octopilot/actions/release@main
  with:
    since_tag: ${{ steps.pre_tag.outputs.tag }}
```

## Logic

1.  Fetches tags.
2.  If `HEAD` is exactly tagged, finds the most recent tag reachable from `HEAD^` (parent).
3.  Otherwise, finds the most recent tag reachable from `HEAD`.
4.  Returns `fallback` input if no tag is found.
