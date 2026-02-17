# Bump Version

Bumps semantic version in project files.

## Supported Modes

-   **Go**: Updates `var Version = "x.y.z"` in `internal/cmd/version.go` (or specified file).
-   **Rust**: Updates `version = "x.y.z"` in `Cargo.toml`.

## Usage

```yaml
- uses: octopilot/actions/bump-version@main
  id: bump
  with:
    mode: go
    bump: minor
```

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `mode` | `go` or `rust` | `go` |
| `bump` | `major`, `minor`, `patch` | `patch` |
| `file` | Path to file | Auto-detected |

## Outputs

| Output | Description |
|--------|-------------|
| `version` | The new version string (e.g. `1.2.3`) |
| `old_version` | The previous version string |
