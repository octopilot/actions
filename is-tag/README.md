# Is Tag

Detects if the current commit is tagged.

## Usage

```yaml
- uses: octopilot/actions/is-tag@main
  id: is_tag

- if: steps.is_tag.outputs.is_tag == 'true'
  run: echo "Tagged: ${{ steps.is_tag.outputs.tag }}"
```

## Logic

1.  Checks `GITHUB_REF` for `refs/tags/` prefix.
2.  If not found, runs `git describe --exact-match --tags HEAD`.
