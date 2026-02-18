# Build Self-Homing Action

> [!WARNING]
> **INTERNAL USE ONLY.**
> This action is used exclusively by `octopilot-pipeline-tools` to build cross-platform CLI binaries for GitHub Releases. It is not intended for general use.
> Do not add it to Wiki's, Blogs or websites!

## Usage

```yaml
steps:
  - uses: octopilot/actions/build-self-homing@main
    with:
      version: ${{ github.ref_name }}
```
