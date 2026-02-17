# octopilot/actions

Official GitHub Actions for the Octopilot ecosystem. This monorepo contains a suite of actions designed to automate GitOps workflows, secret management, and Kubernetes operations.

## Actions

| Action | Description |
|--------|-------------|
| [**setup-tools**](setup-tools/README.md) | Installs standard DevOps CLIs: `kubectl`, `sops`, `kustomize`, and `yq`. |
| [**sops-decrypt**](sops-decrypt/README.md) | Decrypts SOPS-encrypted files (YAML, JSON, dotenv) using GPG or AGE keys. |
| [**rotate-secret**](rotate-secret/README.md) | Securely rotates GitHub repository secrets using LibSodium encryption. |
| [**release**](release/README.md) | Generates AI-summarized release notes from commit history. |
| [**kubernetes-auth**](kubernetes-auth/README.md) | Authenticates with Kubernetes using OIDC (ROPC flow) and sets up `kubeconfig`. |
| [**gke-allow-runner**](network-access/gke-allow-runner/README.md) | Whitelists GitHub Runner IPs in GKE Control Plane authorized networks. |
| [**eks-allow-runner**](network-access/eks-allow-runner/README.md) | Whitelists GitHub Runner IPs in AWS EKS public access CIDRs. |
| [**aks-allow-runner**](network-access/aks-allow-runner/README.md) | Whitelists GitHub Runner IPs in Azure AKS API Server authorized IP ranges. |
| [**octopilot**](octopilot/README.md) | Run Octopilot CLI (`op`) commands as a GitHub Action. |

## Usage

Each action is standalone and can be used directly in your workflows. Please refer to the specific README linked above for inputs, outputs, and examples.

Example usage format:

```yaml
uses: octopilot/actions/<action-name>@main
```

## Development

This is a monorepo. Shared code lives in `common/`.

### Testing

We use `pytest` for unit testing. To run tests locally:

```bash
# Install dependencies
pip install -e ./common pytest pytest-cov ruff

# Run tests
PYTHONPATH=common pytest tests/ -v
```

### Linting

We use `ruff` for linting and formatting:

```bash
ruff check .
ruff format --check .
```
