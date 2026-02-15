# Kubernetes Auth

This GitHub Action authenticates with a Kubernetes cluster using OIDC (Resource Owner Password Credentials flow) and sets up `kubeconfig`.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `oidc_url` | OIDC Provider URL | **Yes** | |
| `oidc_username` | OIDC Client ID / Username | **Yes** | |
| `oidc_password` | OIDC Client Secret / Password | **Yes** | |
| `k8s_url` | Kubernetes API Server URL | **Yes** | |
| `k8s_namespace` | Default Namespace | No | `default` |
| `k8s_skip_tls_verify` | Skip TLS Verification | No | `false` |

## Outputs

Sets the `KUBECONFIG` environment variable to the path of the generated config file.

## Usage

```yaml
steps:
  - name: Authenticate to K8s
    uses: octopilot/actions/kubernetes-auth@main
    with:
      oidc_url: https://oidc.example.com/token
      oidc_username: ${{ secrets.OIDC_CLIENT_ID }}
      oidc_password: ${{ secrets.OIDC_CLIENT_SECRET }}
      k8s_url: https://k8s.example.com

  - name: Run kubectl
    run: kubectl get pods
```
