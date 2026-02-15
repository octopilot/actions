import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock Azure SDKs before importing aks_updater
sys.modules["azure"] = MagicMock()
sys.modules["azure.identity"] = MagicMock()
sys.modules["azure.mgmt.containerservice"] = MagicMock()
sys.modules["azure.core"] = MagicMock()
sys.modules["azure.core.exceptions"] = MagicMock()


# Mock specific exceptions
class ResourceNotFoundError(Exception):
    pass


class HttpResponseError(Exception):
    pass


sys.modules["azure.core.exceptions"].ResourceNotFoundError = ResourceNotFoundError
sys.modules["azure.core.exceptions"].HttpResponseError = HttpResponseError

# Add parent directory to path to import aks_updater
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aks_updater  # noqa: E402


class TestAKSUpdater(unittest.TestCase):
    @patch("aks_updater.requests.get")
    def test_get_public_ip_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ip": "1.2.3.4"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        ip = aks_updater.get_public_ip()
        self.assertEqual(ip, "1.2.3.4")

    @patch("aks_updater.DefaultAzureCredential")
    @patch("aks_updater.ContainerServiceClient")
    def test_update_cluster_access_add_new_ip(self, mock_client_cls, mock_cred_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Mock existing cluster
        mock_cluster = MagicMock()
        mock_cluster.api_server_access_profile.authorized_ip_ranges = ["10.0.0.1/32"]
        mock_client.managed_clusters.get.return_value = mock_cluster

        # Mock update
        mock_poller = MagicMock()
        mock_client.managed_clusters.begin_create_or_update.return_value = mock_poller

        aks_updater.update_cluster_access("sub-123", "rg-test", "my-cluster", "add", "1.2.3.4/32")

        # Verify get called
        mock_client.managed_clusters.get.assert_called_with("rg-test", "my-cluster")

        # Verify update call
        mock_client.managed_clusters.begin_create_or_update.assert_called()
        args = mock_client.managed_clusters.begin_create_or_update.call_args
        self.assertEqual(args[0][0], "rg-test")
        self.assertEqual(args[0][1], "my-cluster")

        # Verify IP added
        updated_cluster = args[0][2]
        new_ranges = updated_cluster.api_server_access_profile.authorized_ip_ranges
        self.assertIn("1.2.3.4/32", new_ranges)
        self.assertIn("10.0.0.1/32", new_ranges)
        self.assertEqual(len(new_ranges), 2)

    @patch("aks_updater.DefaultAzureCredential")
    @patch("aks_updater.ContainerServiceClient")
    def test_update_cluster_access_remove_ip(self, mock_client_cls, mock_cred_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_cluster = MagicMock()
        mock_cluster.api_server_access_profile.authorized_ip_ranges = ["10.0.0.1/32", "1.2.3.4/32"]
        mock_client.managed_clusters.get.return_value = mock_cluster

        mock_poller = MagicMock()
        mock_client.managed_clusters.begin_create_or_update.return_value = mock_poller

        aks_updater.update_cluster_access("sub-123", "rg-test", "my-cluster", "remove", "1.2.3.4/32")

        args = mock_client.managed_clusters.begin_create_or_update.call_args
        updated_cluster = args[0][2]
        new_ranges = updated_cluster.api_server_access_profile.authorized_ip_ranges
        self.assertNotIn("1.2.3.4/32", new_ranges)
        self.assertIn("10.0.0.1/32", new_ranges)

    @patch("aks_updater.DefaultAzureCredential")
    @patch("aks_updater.ContainerServiceClient")
    def test_update_cluster_no_changes_needed(self, mock_client_cls, mock_cred_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        mock_cluster = MagicMock()
        mock_cluster.api_server_access_profile.authorized_ip_ranges = ["1.2.3.4/32"]
        mock_client.managed_clusters.get.return_value = mock_cluster

        aks_updater.update_cluster_access("sub-123", "rg-test", "my-cluster", "add", "1.2.3.4/32")

        mock_client.managed_clusters.begin_create_or_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
