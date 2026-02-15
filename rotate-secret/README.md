# Rotate Secret

This GitHub Action rotates a GitHub Repository Secret using PyNaCl (LibSodium) encryption.

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `secret_name` | Name of the secret to update | **Yes** |
| `secret_value` | New value for the secret | **Yes** |
| `repository` | Repository name (`owner/repo`) | **Yes** |
| `token` | GitHub Token (PAT or GITHUB_TOKEN) with repo scope | **Yes** |

## Usage

```yaml
steps:
  - name: Rotate Secret
    uses: octopilot/actions/rotate-secret@main
    with:
      secret_name: MY_SECRET
      secret_value: ${{ steps.generate-token.outputs.token }}
      repository: ${{ github.repository }}
      token: ${{ secrets.PERSONAL_ACCESS_TOKEN }}
```
