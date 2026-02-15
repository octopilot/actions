# EKS Network Access Action

This action automatically whitelists the GitHub Runner's public IP in your AWS EKS cluster's VPC configuration (`publicAccessCidrs`), allowing the runner to communicate with the Kubernetes API server securely.

## Features

- **Dynamic IP Detection**: Automatically fetches the runner's public IP using `api.ipify.org`.
- **Safe Updates**: Adds the IP to the existing list of authorized CIDRs without overwriting them.
- **Cleanup**: Supports a `remove` mode to clean up the allowed IP after the job.
- **Composite Action**: Runs fast using pre-installed Python on runners.

## Usage

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-region: us-east-1
          role-to-assume: arn:aws:iam::123456789012:role/my-github-actions-role

      - name: Whitelist Runner IP
        uses: octopilot/actions/network-access/eks-allow-runner@main
        with:
          cluster_name: my-production-cluster
          region: us-east-1
          mode: add

      - name: Run kubectl commands
        run: kubectl get pods -A

      - name: Remove Whitelist
        if: always() # Ensure cleanup happens even if previous steps fail
        uses: octopilot/actions/network-access/eks-allow-runner@main
        with:
          cluster_name: my-production-cluster
          region: us-east-1
          mode: remove
```

## Inputs

| Input | Description | Required | Default |
| -- | -- | -- | -- |
| `cluster_name` | Name of the EKS Cluster | **Yes** | |
| `region` | AWS Region (e.g., `us-east-1`) | **Yes** | |
| `mode` | Operation mode: `add` or `remove` | No | `add` |

## Prerequisites

- **AWS Credentials**: The runner must have AWS credentials configured (e.g., via `aws-actions/configure-aws-credentials`) with permissions to:
  - `eks:DescribeCluster`
  - `eks:UpdateClusterConfig`
- **Public Endpoint**: The EKS cluster must have public endpoint access enabled (can be restricted by CIDR, which is what this action manages).
