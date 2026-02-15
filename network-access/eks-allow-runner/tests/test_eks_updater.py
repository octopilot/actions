import os
import sys
import unittest

# Mock boto3 and botocore before importing eks_updater
from unittest.mock import MagicMock, patch

sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()
sys.modules["botocore.exceptions"].ClientError = Exception

# Add parent directory to path to import eks_updater
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eks_updater  # noqa: E402


class TestEKSUpdater(unittest.TestCase):
    @patch("eks_updater.requests.get")
    def test_get_public_ip_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ip": "1.2.3.4"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        ip = eks_updater.get_public_ip()
        self.assertEqual(ip, "1.2.3.4")

    @patch("eks_updater.boto3.client")
    def test_update_cluster_access_add_new_ip(self, mock_boto):
        mock_eks = MagicMock()
        mock_boto.return_value = mock_eks

        # Mocks for describe_cluster
        mock_eks.describe_cluster.return_value = {
            "cluster": {"resourcesVpcConfig": {"endpointPublicAccess": True, "publicAccessCidrs": ["10.0.0.1/32"]}}
        }

        # Mocks for update_cluster_config
        mock_eks.update_cluster_config.return_value = {"update": {"id": "update-123"}}

        # Mocks for describe_update (wait loop)
        mock_eks.describe_update.side_effect = [
            {"update": {"status": "InProgress"}},
            {"update": {"status": "Successful"}},
        ]

        eks_updater.update_cluster_access("my-cluster", "us-east-1", "add", "1.2.3.4/32")

        # Verify describe_cluster called
        mock_eks.describe_cluster.assert_called_with(name="my-cluster")

        # Verify update_cluster_config called with both IPs
        call_args = mock_eks.update_cluster_config.call_args
        self.assertEqual(call_args[1]["name"], "my-cluster")
        cidrs = call_args[1]["resourcesVpcConfig"]["publicAccessCidrs"]
        self.assertIn("1.2.3.4/32", cidrs)
        self.assertIn("10.0.0.1/32", cidrs)
        self.assertEqual(len(cidrs), 2)

    @patch("eks_updater.boto3.client")
    def test_update_cluster_access_remove_ip(self, mock_boto):
        mock_eks = MagicMock()
        mock_boto.return_value = mock_eks

        mock_eks.describe_cluster.return_value = {
            "cluster": {
                "resourcesVpcConfig": {"endpointPublicAccess": True, "publicAccessCidrs": ["10.0.0.1/32", "1.2.3.4/32"]}
            }
        }

        mock_eks.update_cluster_config.return_value = {"update": {"id": "update-123"}}

        mock_eks.describe_update.return_value = {"update": {"status": "Successful"}}

        eks_updater.update_cluster_access("my-cluster", "us-east-1", "remove", "1.2.3.4/32")

        # Verify update called with only remaining IP
        mock_eks.update_cluster_config.assert_called_with(
            name="my-cluster", resourcesVpcConfig={"publicAccessCidrs": ["10.0.0.1/32"]}
        )

    @patch("eks_updater.boto3.client")
    def test_update_cluster_no_changes_needed(self, mock_boto):
        mock_eks = MagicMock()
        mock_boto.return_value = mock_eks

        mock_eks.describe_cluster.return_value = {
            "cluster": {"resourcesVpcConfig": {"endpointPublicAccess": True, "publicAccessCidrs": ["1.2.3.4/32"]}}
        }

        eks_updater.update_cluster_access("my-cluster", "us-east-1", "add", "1.2.3.4/32")

        mock_eks.update_cluster_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
