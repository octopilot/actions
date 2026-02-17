# Bump Version

Bumps semantic version in project files.

## Supported Modes

-   **Go**: Updates `var Version = "x.y.z"` in `internal/cmd/version.go` (or specified file).
-   **Rust**: Updates `version = "x.y.z"` in `Cargo.toml`.
-   **Maven**: Updates `<version>x.y.z</version>` in `pom.xml`.
-   **Gradle**: Updates `version=x.y.z` in `gradle.properties` or `version = 'x.y.z'` in `build.gradle`.

## Usage

```yaml
- uses: octopilot/actions/bump-version@main
  id: bump
  with:
    mode: go # go, rust, maven, gradle
    bump: minor
```

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `mode` | `go`, `rust`, `maven`, `gradle` | `go` |
| `bump` | `major`, `minor`, `patch` | `patch` |
| `file` | Path to version file. Auto-detected based on mode. | |

## Outputs

| Output | Description |
|--------|-------------|
| `version` | The new version string (e.g. `1.2.3`) |
| `old_version` | The previous version string |
