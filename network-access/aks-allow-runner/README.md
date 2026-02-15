# AKS Network Access Action

This action automatically whitelists the GitHub Runner's public IP in your Azure Kubernetes Service (AKS) cluster's API Server Authorized IP Ranges.

## Features

- **Dynamic IP Detection**: Fetches the runner's public IP.
- **Safe Updates**: Adds the IP to the existing `authorized_ip_ranges` without overwriting others.
- **Cleanup**: `remove` mode ensures the IP is removed after the job.
- **Zero-touch Auth**: Uses `azure/login` credentials automatically.

## Usage

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Whitelist Runner IP
        uses: octopilot/actions/network-access/aks-allow-runner@main
        with:
          resource_group: my-resource-group
          cluster_name: my-aks-cluster
          subscription_id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
          mode: add

      - name: Run kubectl commands
        run: kubectl get pods -n production

      - name: Remove Whitelist
        if: always()
        uses: octopilot/actions/network-access/aks-allow-runner@main
        with:
          resource_group: my-resource-group
          cluster_name: my-aks-cluster
          subscription_id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
          mode: remove
```

## Inputs

| Input | Description | Required | Default |
| -- | -- | -- | -- |
| `resource_group` | Azure Resource Group containing the cluster | **Yes** | |
| `cluster_name` | Name of the AKS Cluster | **Yes** | |
| `subscription_id` | Azure Subscription ID | **Yes** | |
| `mode` | Operation mode: `add` or `remove` | No | `add` |

## Prerequisites

- **Azure Login**: You must run `azure/login` before this step.
- **Permissions**: The Service Principal/Identity must have `Microsoft.ContainerService/managedClusters/write` permission (Contributor or similar).
