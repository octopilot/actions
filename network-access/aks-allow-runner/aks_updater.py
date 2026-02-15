import os
import sys

import requests
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.mgmt.containerservice import ContainerServiceClient


def get_public_ip():
    """Fetch the public IP of the runner."""
    print("Fetching public IP...")
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=10)
        response.raise_for_status()
        ip = response.json()["ip"]
        print(f"Detected Public IP: {ip}")
        return ip
    except Exception as e:
        print(f"Failed to get public IP: {e}", file=sys.stderr)
        sys.exit(1)


def update_cluster_access(subscription_id, resource_group, cluster_name, mode, ip_cidr):
    """Update AKS cluster authorized IP ranges."""
    print(f"Authenticating to Azure for subscription {subscription_id}...")
    try:
        credential = DefaultAzureCredential()
        client = ContainerServiceClient(credential, subscription_id)
    except Exception as e:
        print(f"Failed to create Azure client: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching cluster {cluster_name} in {resource_group}...")
    try:
        cluster = client.managed_clusters.get(resource_group, cluster_name)
    except ResourceNotFoundError:
        print(f"Cluster {cluster_name} not found in {resource_group}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Failed to get cluster: {e}", file=sys.stderr)
        sys.exit(1)

    # Check api_server_access_profile
    profile = cluster.api_server_access_profile
    if not profile or profile.enable_private_cluster is not False:
        # Actually logic is complex: enable_private_cluster=True means private.
        # But authorized_ip_ranges is only relevant for public clusters usually,
        # or private clusters with public DNS?
        # Azure API allows setting it. If it's None, it means open to 0.0.0.0/0?
        pass

    current_ranges = []
    if profile and profile.authorized_ip_ranges:
        current_ranges = list(profile.authorized_ip_ranges)

    # If None, it might mean "allow all" or "unconfigured".
    # Assuming we want to manage it explicitly.

    new_ranges = set(current_ranges)

    # Logic to handle 0.0.0.0/0 if it exists?
    # For now, treat as list of strings.

    if mode == "add":
        print(f"Adding {ip_cidr} to authorized networks...")
        if ip_cidr in new_ranges:
            print("IP already in authorized networks.")
            return
        new_ranges.add(ip_cidr)

    elif mode == "remove":
        print(f"Removing {ip_cidr} from authorized networks...")
        if ip_cidr not in new_ranges:
            print("IP not found in authorized networks, nothing to remove.")
            return
        new_ranges.remove(ip_cidr)

    if set(current_ranges) == new_ranges:
        print("No changes needed.")
        return

    # Update cluster
    print("Sending update request...")

    # We need to construct the update parameter.
    # Usually we can modify the object and pass it back, or pass a dict/model with changes.
    # ManagedCluster usually requires just the changed fields if using PATCH (update_tags)
    # but typically PUT needs full object or ManagedCluster type.
    # However, create_or_update is PUT. existing cluster object should be used.

    cluster.api_server_access_profile.authorized_ip_ranges = list(new_ranges)

    try:
        poller = client.managed_clusters.begin_create_or_update(resource_group, cluster_name, cluster)
        print("Waiting for operation to complete...")
        poller.result()
        print("Operation completed successfully.")
    except HttpResponseError as e:
        print(f"Failed to update cluster: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    resource_group = os.environ.get("INPUT_RESOURCE_GROUP")
    cluster_name = os.environ.get("INPUT_CLUSTER_NAME")
    subscription_id = os.environ.get("INPUT_SUBSCRIPTION_ID")
    mode = os.environ.get("INPUT_MODE", "add")

    if not all([resource_group, cluster_name, subscription_id]):
        print("Error: Missing required inputs.", file=sys.stderr)
        sys.exit(1)

    ip = get_public_ip()
    # AKS might accept IP or CIDR. Usually CIDR /32 for single IP.
    ip_cidr = f"{ip}/32"

    update_cluster_access(subscription_id, resource_group, cluster_name, mode, ip_cidr)


if __name__ == "__main__":
    main()
