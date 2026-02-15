import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_kubernetes


@pytest.fixture
def mock_env():
    with patch.dict(
        os.environ,
        {
            "INPUT_OIDC_URL": "https://oidc.example.com/token",
            "INPUT_OIDC_USERNAME": "my-client",
            "INPUT_OIDC_PASSWORD": "my-secret",
            "INPUT_K8S_URL": "https://k8s.example.com",
            "INPUT_K8S_NAMESPACE": "my-ns",
            "INPUT_K8S_SKIP_TLS_VERIFY": "true",
            "RUNNER_TEMP": "/tmp/runner",
        },
        clear=True,
    ):
        yield


@patch("auth_kubernetes.requests.post")
@patch("auth_kubernetes.os.makedirs")
@patch("builtins.open", new_callable=MagicMock)
def test_main_flow(mock_open, mock_makedirs, mock_post, mock_env):
    # Mock OIDC Response
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"access_token": "mock-token-123"}

    auth_kubernetes.main()

    # Verify OIDC Call
    mock_post.assert_called_with(
        "https://oidc.example.com/token",
        headers={
            "Authorization": "Basic bXktY2xpZW50Om15LXNlY3JldA==",  # base64(my-client:my-secret)
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"client_id": "my-client"},
        timeout=10,
    )

    # Verify config writing
    # We expect a write to a file in /tmp/runner/kube_config_<timestamp>/custom-config
    # Since timestamp varies, we check if open was called
    assert mock_open.called

    # We can inspect what was written to the config file
    # The second call to open might be GITHUB_ENV if provided?
    # Actually mock_env set INPUT vars. Let's add GITHUB_ENV to mock_env.


@patch("auth_kubernetes.requests.post")
@patch("auth_kubernetes.create_kubeconfig")
def test_create_config_call(mock_create_config, mock_post, mock_env):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"access_token": "token"}
    mock_create_config.return_value = "/path/to/config"

    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        os.environ["GITHUB_ENV"] = "/tmp/env"
        auth_kubernetes.main()

        # Verify call arguments to create_kubeconfig
        mock_create_config.assert_called_with(
            "token", "https://oidc.example.com/token", "my-client", "https://k8s.example.com", "my-ns", True
        )

        # Verify env write
        mock_open.assert_called_with("/tmp/env", "a")
        mock_open.return_value.__enter__.return_value.write.assert_called_with("KUBECONFIG=/path/to/config\n")
