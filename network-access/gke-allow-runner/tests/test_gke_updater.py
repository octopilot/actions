import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gke_updater


@pytest.fixture
def mock_env():
    with patch.dict(
        os.environ,
        {
            "INPUT_PROJECT_ID": "my-project",
            "INPUT_LOCATION": "europe-west1",
            "INPUT_CLUSTER_NAME": "my-cluster",
            "INPUT_MODE": "add",
            "INPUT_DESCRIPTION": "Test Runner",
        },
        clear=True,
    ):
        yield


@patch("gke_updater.requests.get")
@patch("gke_updater.container_v1")
def test_add_ip(mock_container, mock_get, mock_env):
    # Mock IP retrieval
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"ip": "1.2.3.4"}

    # Mock GKE Client
    mock_client = mock_container.ClusterManagerClient.return_value

    # Mock get_cluster response
    mock_cluster = MagicMock()
    # Initial networks
    mock_cluster.master_authorized_networks_config.cidr_blocks = []
    mock_client.get_cluster.return_value = mock_cluster

    # Mock update_cluster response
    mock_op = MagicMock()
    mock_op.name = "op-123"
    mock_client.update_cluster.return_value = mock_op

    # Mock Operation Status
    mock_container.Operation.Status.DONE = 1
    mock_client.get_operation.return_value.status = 1
    mock_client.get_operation.return_value.error = None

    # Mock MasterAuthorizedNetworksConfig constructor
    # The code calls: container_v1.MasterAuthorizedNetworksConfig.CidrBlock(...)
    # We need to make sure this returns a mock or object we can check
    mock_cidr_block = MagicMock()
    mock_cidr_block.cidr_block = "1.2.3.4/32"
    mock_cidr_block.display_name = "Test Runner"
    mock_container.MasterAuthorizedNetworksConfig.CidrBlock.return_value = mock_cidr_block

    gke_updater.main()

    # Verify IP fetch
    mock_get.assert_called_with("https://api.ipify.org?format=json", timeout=10)

    # Verify Cluster Fetch
    mock_client.get_cluster.assert_called_with(name="projects/my-project/locations/europe-west1/clusters/my-cluster")

    # Verify Update Call
    mock_client.update_cluster.assert_called()
    call_args = mock_client.update_cluster.call_args
    assert call_args.kwargs["name"] == "projects/my-project/locations/europe-west1/clusters/my-cluster"

    # Verify ClusterUpdate was initialized
    mock_container.ClusterUpdate.assert_called()
    update_kwargs = mock_container.ClusterUpdate.call_args.kwargs

    # Verify usage of config
    # The code passes desired_master_authorized_networks_config=authorized_networks
    # Check if that object has our new block
    config_passed = update_kwargs["desired_master_authorized_networks_config"]
    # In our mock setup, existing_blocks was retrieved from mock_cluster.master_authorized_networks_config.cidr_blocks
    # And we appended to it.
    # Since `existing_blocks = list(...)` makes a copy, we need to check if
    # authorized_networks.cidr_blocks was updated in the code.
    # Code: authorized_networks.cidr_blocks = existing_blocks
    # So config_passed (which is authorized_networks) should have the new list.
    assert len(config_passed.cidr_blocks) == 1
    assert config_passed.cidr_blocks[0] == mock_cidr_block


@patch("gke_updater.requests.get")
@patch("gke_updater.container_v1")
def test_remove_ip(mock_container, mock_get):
    with patch.dict(
        os.environ, {"INPUT_PROJECT_ID": "p", "INPUT_LOCATION": "l", "INPUT_CLUSTER_NAME": "c", "INPUT_MODE": "remove"}
    ):
        mock_get.return_value.json.return_value = {"ip": "1.2.3.4"}
        mock_client = mock_container.ClusterManagerClient.return_value

        mock_cluster = MagicMock()
        # Mock existing block with our IP
        block = MagicMock()
        block.cidr_block = "1.2.3.4/32"
        mock_cluster.master_authorized_networks_config.cidr_blocks = [block]
        mock_client.get_cluster.return_value = mock_cluster

        mock_op = MagicMock()
        mock_op.name = "op-remove"
        mock_client.update_cluster.return_value = mock_op

        mock_container.Operation.Status.DONE = 1
        mock_client.get_operation.return_value.status = 1
        mock_client.get_operation.return_value.error = None

        gke_updater.main()

        # Verify update called
        mock_client.update_cluster.assert_called()
        # Check ClusterUpdate init
        mock_container.ClusterUpdate.assert_called()
        update_kwargs = mock_container.ClusterUpdate.call_args.kwargs
        config_passed = update_kwargs["desired_master_authorized_networks_config"]
        # Should be empty now
        assert len(config_passed.cidr_blocks) == 0
