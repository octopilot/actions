# SOPS Decrypt

This GitHub Action decrypts a SOPS-encrypted file using GPG or AGE keys.

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `file` | Path to the encrypted file | **Yes** | |
| `gpg_key` | Base64 encoded GPG private key | No | |
| `age_key` | AGE private key | No | |
| `output_type` | Output format (`json`, `yaml`, `dotenv`, `binary`) | No | `json` |
| `version` | SOPS version to use (not currently implemented in Python version, uses system sops) | No | `latest` |

## Outputs

| Output | Description |
|--------|-------------|
| `data` | The decrypted data |

## Usage

```yaml
steps:
  - uses: actions/checkout@v4
  
  - name: Decrypt secrets
    id: secrets
    uses: octopilot/actions/sops-decrypt@main
    with:
      file: secrets.enc.yaml
      age_key: ${{ secrets.SOPS_AGE_KEY }}
      output_type: json

  - name: Use secrets
    run: echo "Secret is ${{ fromJson(steps.secrets.outputs.data).my_secret }}"
```
