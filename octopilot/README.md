# octopilot/octopilot

Run Octopilot CLI (`op`) commands as a GitHub Action.

## Usage

```yaml
steps:
  - name: Build and Push
    uses: octopilot/actions/octopilot@main
    with:
      command: build
      # Note: Arguments must be compatible with the op CLI
      args: --push --repo ghcr.io/my-org/my-repo
```

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `command` | The `op` command to execute (e.g. `build`, `version`). | `help` |
| `args` | Additional arguments for the command. | `""` |
