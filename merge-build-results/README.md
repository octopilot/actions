# merge-build-results

Merges multiple `build_result.json` files (from fanned-out integration jobs) into a single file without data loss.

## When to use

When the workflow fans out (e.g. matrix) and each job runs an Octopilot build (or legacy docker/paketo/helm-to-ttl-sh), each job produces its own `build_result.json`. The receiving job downloads all integration artifacts and must merge those JSON files so downstream steps see one combined result.

## Behaviour

- **Finds** all files named `build_result.json` under the given directory (e.g. after `download-artifact` with `pattern: integration-*`).
- **Merges** by concatenating every `builds[]` entry from every file, in sorted file order. No deduplication (same `imageName` can appear with different `tag` from different jobs).
- **Writes** a single `build_result.json` to the given output path. If no files are found, writes `{"builds":[]}`.

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `directory` | No | `artifact-outputs` | Directory to search for `build_result.json` (e.g. download-artifact path). |
| `output-path` | No | `build_result.json` | Path for the merged file. |

## Outputs

| Output | Description |
|--------|-------------|
| `path` | Path to the merged `build_result.json`. |
| `count` | Number of build entries in the merged result. |

## Example (workflow)

```yaml
- uses: actions/download-artifact@v4
  with:
    pattern: integration-*
    path: artifact-outputs

- uses: octopilot/actions/merge-build-results@main
  with:
    directory: artifact-outputs
    output-path: build_result.json
```

Each integration artifact should contain a `build_result.json` (e.g. by uploading the workspace directory that includes it after the Octopilot action).
