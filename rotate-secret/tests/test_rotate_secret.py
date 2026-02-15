import base64
import os
import sys
from unittest.mock import patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rotate_secret


@pytest.fixture
def mock_env():
    with patch.dict(
        os.environ,
        {
            "INPUT_SECRET_NAME": "MY_SECRET",
            "INPUT_SECRET_VALUE": "super_secret_value",
            "INPUT_REPOSITORY": "owner/repo",
            "INPUT_TOKEN": "ghp_token",
        },
        clear=True,
    ):
        yield


@patch("rotate_secret.requests.get")
@patch("rotate_secret.requests.put")
@patch("rotate_secret.encrypt_secret")
def test_main_flow(mock_encrypt, mock_put, mock_get, mock_env):
    # Mock Public Key response
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"key": "base64_public_key", "key_id": "12345"}

    # Mock Encryption
    mock_encrypt.return_value = "encrypted_base64_string"

    # Mock Update response
    mock_put.return_value.status_code = 204

    rotate_secret.main()

    # Verify Get Key
    mock_get.assert_called_with(
        "https://api.github.com/repos/owner/repo/actions/secrets/public-key",
        headers={"Authorization": "Bearer ghp_token", "Accept": "application/vnd.github.v3+json"},
        timeout=10,
    )

    # Verify Encrypt call (we mocked it, but we check if it was called with correct key)
    # Since we mocked encrypt_secret, we check arguments passed to it
    mock_encrypt.assert_called_with("base64_public_key", "super_secret_value")

    # Verify Put Secret
    mock_put.assert_called_with(
        "https://api.github.com/repos/owner/repo/actions/secrets/MY_SECRET",
        headers={"Authorization": "Bearer ghp_token", "Accept": "application/vnd.github.v3+json"},
        json={"encrypted_value": "encrypted_base64_string", "key_id": "12345"},
        timeout=10,
    )


def test_encrypt_secret_integration():
    # We can test the actual encryption if we have a valid public key pair,
    # or we can trust PyNaCl.
    # Let's generate a keypair for testing
    from nacl import encoding, public

    # Generate a receiver key pair
    private_key = public.PrivateKey.generate()
    public_key = private_key.public_key
    public_key_b64 = public_key.encode(encoding.Base64Encoder).decode("utf-8")

    secret_value = "my_test_secret"

    # Encrypt
    encrypted_b64 = rotate_secret.encrypt_secret(public_key_b64, secret_value)

    # Decrypt to verify
    sealed_box = public.SealedBox(private_key)
    encrypted_bytes = base64.b64decode(encrypted_b64)
    decrypted = sealed_box.decrypt(encrypted_bytes).decode("utf-8")

    assert decrypted == secret_value
