# Kotlin lint (ktlint)

Runs [ktlint](https://github.com/pinterest/ktlint) with a Checkstyle XML report and publishes annotations using [GitHub Action for ktlint](https://github.com/marketplace/actions/github-action-for-ktlint) (`yutailang0119/action-ktlint`).

This composite action is **standalone**: it does not require Octopilot, `detect-contexts`, or any other pipeline wiring—only `actions/checkout` and this action.

## Standalone workflow (plain Kotlin repo)

Add a workflow under `.github/workflows/` (for example `ktlint.yml`). Adjust `paths` to match your layout.

```yaml
name: ktlint

on:
  push:
    branches: [main, master]
    paths:
      - '**.kt'
      - '**.kts'
      - '.editorconfig'
      - '.github/workflows/ktlint.yml'
  pull_request:
    paths:
      - '**.kt'
      - '**.kts'
      - '.editorconfig'
      - '.github/workflows/ktlint.yml'

permissions:
  contents: read
  checks: write

jobs:
  ktlint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Option A — reference this action from the octopilot/actions repo (tag or branch)
      - uses: octopilot/actions/kotlin-lint@main

      # Option B — vendor: copy the kotlin-lint folder into your repo, e.g. .github/actions/kotlin-lint
      # - uses: ./.github/actions/kotlin-lint
```

No Gradle, Docker, or Octopilot services are required. Put `.editorconfig` or `.ktlint` config in the repo root (or under `working-directory`) if you want project-specific rules.

### Kotlin in a subfolder

Set `working-directory` when sources live under a path (for example a monorepo package):

```yaml
      - uses: octopilot/actions/kotlin-lint@main
        with:
          working-directory: packages/my-kotlin-lib
```

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `working-directory` | Directory where ktlint runs (`.` = repo root, or a subfolder) | `.` |
| `ktlint-version` | ktlint release tag from pinterest/ktlint | `1.7.1` |
| `ignore-warnings` | Ignore warning-severity findings in annotations | `true` |
| `report-directory` | Directory for the Checkstyle XML report (relative to `working-directory`) | `build` |
| `report-filename` | Report filename under `report-directory` | `ktlint-report.xml` |
| `kotlin-extra-args` | Extra arguments passed to `ktlint` | _(empty)_ |
| `fail-on-error` | Fail the job when the report contains errors | `true` |

## Behaviour

1. Installs the ktlint binary for the requested version.
2. Runs `ktlint` with `--reporter=checkstyle,output=…` under `working-directory` (`continue-on-error` on that step so the XML is still produced when there are findings).
3. Runs `action-ktlint` on the report path and fails the job by default when errors are present.

For **Android / Gradle** projects that use `./gradlew ktlintCheck`, prefer calling Gradle in your workflow instead of this action, so CI matches your plugin configuration.
