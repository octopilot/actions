import os
import sys
import time

import requests
from google.cloud import container_v1


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


def wait_for_operation(client, project_id, location, op_id):
    """Wait for a GKE operation to complete."""
    print(f"Waiting for operation {op_id} to complete...")
    operation_name = f"projects/{project_id}/locations/{location}/operations/{op_id}"

    while True:
        op = client.get_operation(name=operation_name)
        if op.status == container_v1.Operation.Status.DONE:
            if op.error:
                print(f"Operation failed: {op.error}", file=sys.stderr)
                sys.exit(1)
            print("Operation completed successfully.")
            return

        print("Operation still running, sleeping 5s...")
        time.sleep(5)


def update_cluster_networks(project_id, location, cluster_name, mode, description, ip_cidr):
    """Update the cluster authorized networks."""
    client = container_v1.ClusterManagerClient()
    name = f"projects/{project_id}/locations/{location}/clusters/{cluster_name}"

    print(f"Fetching cluster {name}...")
    try:
        cluster = client.get_cluster(name=name)
    except Exception as e:
        print(f"Failed to get cluster: {e}", file=sys.stderr)
        sys.exit(1)

    authorized_networks = cluster.master_authorized_networks_config

    # Ensure config exists
    if not authorized_networks:
        print("Master authorized networks config is missing or disabled.", file=sys.stderr)
        sys.exit(1)

    existing_blocks = list(authorized_networks.cidr_blocks)

    if mode == "add":
        print(f"Adding {ip_cidr} to authorized networks...")
        # Check if already exists
        for block in existing_blocks:
            if block.cidr_block == ip_cidr:
                print("IP already in authorized networks.")
                return

        new_block = container_v1.MasterAuthorizedNetworksConfig.CidrBlock(display_name=description, cidr_block=ip_cidr)
        existing_blocks.append(new_block)

    elif mode == "remove":
        print(f"Removing {ip_cidr} from authorized networks...")
        original_len = len(existing_blocks)
        existing_blocks = [b for b in existing_blocks if b.cidr_block != ip_cidr]

        if len(existing_blocks) == original_len:
            print("IP not found in authorized networks, nothing to remove.")
            return

    # Update logic
    authorized_networks.cidr_blocks = existing_blocks

    update = container_v1.ClusterUpdate(desired_master_authorized_networks_config=authorized_networks)

    print("Sending update request...")
    try:
        op = client.update_cluster(name=name, update=update)
        wait_for_operation(client, project_id, location, op.name)
    except Exception as e:
        print(f"Failed to update cluster: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    project_id = os.environ.get("INPUT_PROJECT_ID")
    location = os.environ.get("INPUT_LOCATION")
    cluster_name = os.environ.get("INPUT_CLUSTER_NAME")
    mode = os.environ.get("INPUT_MODE", "add")
    description = os.environ.get("INPUT_DESCRIPTION", "GitHub Action runner")

    if not all([project_id, location, cluster_name]):
        print("Error: Missing required inputs.", file=sys.stderr)
        sys.exit(1)

    ip = get_public_ip()
    ip_cidr = f"{ip}/32"

    update_cluster_networks(project_id, location, cluster_name, mode, description, ip_cidr)


if __name__ == "__main__":
    main()
