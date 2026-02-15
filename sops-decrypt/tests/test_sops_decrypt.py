import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory to path to import sops_decrypt
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sops_decrypt


@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {"INPUT_FILE": "secrets.enc.yaml", "INPUT_OUTPUT_TYPE": "json"}, clear=True):
        yield


@patch("subprocess.run")
@patch("os.path.exists")
def test_decrypt_file_success(mock_exists, mock_run, mock_env):
    mock_exists.return_value = True
    mock_run.return_value.stdout = '{"secret": "value"}'

    with patch("builtins.open", new_callable=MagicMock):
        # Simulate GITHUB_OUTPUT
        os.environ["GITHUB_OUTPUT"] = "/tmp/github_output"

        sops_decrypt.decrypt_file()

        # verification
        mock_run.assert_called_with(
            ["sops", "--decrypt", "--output-type", "json", "secrets.enc.yaml"],
            capture_output=True,
            check=True,
            text=True,
        )


@patch("subprocess.run")
def test_setup_keys_gpg(mock_run):
    # Valid base64 encoding of "test key"
    valid_base64 = "dGVzdCBrZXk="
    with patch.dict(os.environ, {"INPUT_GPG_KEY": valid_base64}):
        sops_decrypt.setup_keys()
        mock_run.assert_called()
        args = mock_run.call_args[0][0]
        assert args == ["gpg", "--import"]


def test_setup_keys_age():
    with patch.dict(os.environ, {"INPUT_AGE_KEY": "age-key-val"}):
        sops_decrypt.setup_keys()
        assert os.environ["SOPS_AGE_KEY"] == "age-key-val"
