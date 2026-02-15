# Setup Tools

This GitHub Action installs common DevOps tools: `kubectl`, `sops`, `kustomize`, and `yq`.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `kubectl_version` | Version of kubectl | No | `v1.32.0` |
| `sops_version` | Version of sops | No | `v3.9.4` |
| `kustomize_version` | Version of kustomize | No | `v5.6.0` |
| `yq_version` | Version of yq | No | `v4.45.1` |

## Usage

```yaml
steps:
  - name: Install Tools
    uses: octopilot/actions/setup-tools@main
    with:
      kubectl_version: v1.28.0

  - name: Check tools
    run: |
      kubectl version --client
      sops --version
```
