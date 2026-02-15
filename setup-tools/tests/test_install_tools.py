import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import install_tools


@pytest.fixture
def mock_env():
    with patch.dict(
        os.environ,
        {
            "GITHUB_WORKSPACE": "/tmp/workspace",
            "GITHUB_PATH": "/tmp/github_path",
            "KUSTOMIZE_VERSION": "5.0.0",
            "SOPS_VERSION": "3.8.0",
            "YQ_VERSION": "4.0.0",
            "KUBECTL_VERSION": "1.20.0",
        },
        clear=True,
    ):
        yield


@patch("install_tools.platform.system")
@patch("install_tools.platform.machine")
@patch("urllib.request.urlretrieve")
@patch("os.makedirs")
@patch("os.chmod")
@patch("os.stat")
@patch("os.remove")
@patch("subprocess.run")
@patch("builtins.open", new_callable=MagicMock)
def test_main_calls_installers(
    mock_open,
    mock_run,
    mock_remove,
    mock_stat,
    mock_chmod,
    mock_makedirs,
    mock_urlretrieve,
    mock_machine,
    mock_system,
    mock_env,
):
    mock_system.return_value = "Darwin"
    mock_machine.return_value = "x86_64"
    mock_stat.return_value.st_mode = 0o644

    install_tools.main()

    # Verify downloads
    assert mock_urlretrieve.call_count == 4

    # Verify kustomize extraction
    mock_run.assert_called_with(
        ["tar", "-xzf", "/tmp/workspace/.bin/kustomize_v5.0.0_darwin_amd64.tar.gz", "-C", "/tmp/workspace/.bin"],
        check=True,
    )

    # Verify path update
    mock_open.assert_called_with("/tmp/github_path", "a")
    mock_open.return_value.__enter__.return_value.write.assert_called_with("/tmp/workspace/.bin\n")


@patch("install_tools.platform.system")
@patch("install_tools.platform.machine")
def test_url_construction_linux_amd64(mock_machine, mock_system):
    mock_system.return_value = "Linux"
    mock_machine.return_value = "x86_64"

    # We can test individual installation functions or just trust main covers them
    # Let's test install_kubectl construction
    with patch("install_tools.download_file") as mock_dl, patch("install_tools.make_executable"):
        install_tools.install_kubectl("1.25.0", "/bin")

        mock_dl.assert_called_with("https://dl.k8s.io/release/v1.25.0/bin/linux/amd64/kubectl", "/bin/kubectl")
