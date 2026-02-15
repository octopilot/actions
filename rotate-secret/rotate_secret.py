import base64
import os
import sys

import requests
from nacl import public


def get_public_key(repo, token):
    """Fetch the repository public key."""
    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Error fetching public key: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)

    return response.json()


def encrypt_secret(public_key, secret_value):
    """Encrypt the secret value using LibSodium SealedBox."""
    public_key_bytes = base64.b64decode(public_key)
    sealed_box = public.SealedBox(public.PublicKey(public_key_bytes))
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def update_secret(repo, token, secret_name, encrypted_value, key_id):
    """Update the repository secret."""
    url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    data = {"encrypted_value": encrypted_value, "key_id": key_id}

    response = requests.put(url, headers=headers, json=data, timeout=10)

    if response.status_code not in [201, 204]:
        print(f"Error updating secret: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)

    print(f"Successfully updated secret '{secret_name}' in '{repo}'")


def main():
    secret_name = os.environ.get("INPUT_SECRET_NAME")
    secret_value = os.environ.get("INPUT_SECRET_VALUE")
    repo = os.environ.get("INPUT_REPOSITORY")
    token = os.environ.get("INPUT_TOKEN")

    if not all([secret_name, secret_value, repo, token]):
        print("Error: Missing required inputs (secret_name, secret_value, repository, token)", file=sys.stderr)
        sys.exit(1)

    print(f"Rotating secret '{secret_name}' in '{repo}'...")

    # 1. Get Public Key
    key_data = get_public_key(repo, token)
    public_key = key_data["key"]
    key_id = key_data["key_id"]

    # 2. Encrypt
    encrypted_value = encrypt_secret(public_key, secret_value)

    # 3. Update
    update_secret(repo, token, secret_name, encrypted_value, key_id)


if __name__ == "__main__":
    main()
