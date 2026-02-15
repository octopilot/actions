# GKE Allow Runner

This GitHub Action whitelists the GitHub Runner's public IP in a GKE Cluster's Authorized Networks.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `project_id` | GCP Project ID | **Yes** | |
| `location` | GKE Cluster Location (Region/Zone) | **Yes** | |
| `cluster_name` | GKE Cluster Name | **Yes** | |
| `mode` | Operation mode (`add` or `remove`) | No | `add` |
| `description` | Description for the whitelist entry | No | `GitHub Action runner` |
| `service_account_key` | GCP Service Account Key (JSON) for auth | No | |

## Usage

```yaml
steps:
  - name: Whitelist Runner IP
    uses: octopilot/actions/network-access/gke-allow-runner@main
    with:
      project_id: my-project
      location: europe-west1
      cluster_name: my-cluster
      mode: add
      service_account_key: ${{ secrets.GCP_SA_KEY }}

  - name: Run kubectl
    run: kubectl get pods

  - name: Remove Whitelist
    if: always()
    uses: octopilot/actions/network-access/gke-allow-runner@main
    with:
      project_id: my-project
      location: europe-west1
      cluster_name: my-cluster
      mode: remove
      service_account_key: ${{ secrets.GCP_SA_KEY }}
```
