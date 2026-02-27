# setup-flux

Sets up the Flux CLI, installs Flux in the current cluster (`flux install --export`), and applies the exported components. Use this after creating a cluster (e.g. Kind) when you want Flux controllers (source-controller, helm-controller, etc.) installed and ready.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `export_path` | Path to write `flux install --export` output (directory is created if needed). | Yes | - |
| `version` | Flux CLI version. | No | `latest` |

## Behaviour

1. Installs the Flux CLI via [fluxcd/flux2/action](https://github.com/fluxcd/flux2/tree/main/action).
2. Runs `flux install --export` and writes the manifest to `export_path`.
3. Applies the manifest with `kubectl apply`.
4. Waits for `source-controller` and `helm-controller` pods in `flux-system` to be ready (up to 120s each).

Requires a kubeconfig targeting the cluster (e.g. set by a prior Kind or cluster-creation step).

## Usage

```yaml
- name: Create Kind cluster
  uses: helm/kind-action@v1
  with:
    cluster_name: my-cluster

- name: Setup Flux in Kind
  uses: octopilot/actions/setup-flux@main
  with:
    export_path: k8s/deployment/flux-system/gotk-components.yaml
    # version: "latest"  # optional
```

After this step you can deploy Flux resources (e.g. `OCIRepository`, `HelmRelease`) and run `flux reconcile`.
