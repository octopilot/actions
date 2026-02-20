# Build Self-Homing Action

> [!WARNING]
> **INTERNAL USE ONLY.**
> This action is used exclusively by `octopilot/octopilot-pipeline-tools` to
> cross-compile the `op` CLI binary for GitHub Releases.
>
> - Do **not** reference this action in external documentation, the website, blogs, or wikis.
> - Do **not** use this action in third-party repositories — it has no stable public interface.
> - It exists solely to self-home octopilot's own release pipeline.

## What it does

Cross-compiles the `op` binary for all supported platforms and writes the outputs
to a configurable `dist/` directory:

| Platform | Output |
|----------|--------|
| linux/amd64 | `dist/op-linux-amd64` |
| linux/arm64 | `dist/op-linux-arm64` |
| darwin/amd64 | `dist/op-darwin-amd64` |
| darwin/arm64 | `dist/op-darwin-arm64` |

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `version` | ✅ | — | Version string injected via `-ldflags` (e.g. `v1.2.3`) |
| `output_dir` | ❌ | `dist` | Directory to write compiled binaries |

## Internal usage

```yaml
# Used only in octopilot/octopilot-pipeline-tools CI
- uses: octopilot/actions/build-self-homing@main
  with:
    version: ${{ github.ref_name }}
```
