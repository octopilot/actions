import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError


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


def wait_for_update(eks_client, cluster_name, update_id):
    """Wait for EKS update to complete."""
    print(f"Waiting for update {update_id} to complete...")
    while True:
        try:
            update = eks_client.describe_update(name=cluster_name, updateId=update_id)
            status = update["update"]["status"]
            if status == "Successful":
                print("Update completed successfully.")
                return
            elif status == "Failed":
                print(f"Update failed: {update['update'].get('errors')}", file=sys.stderr)
                sys.exit(1)
            elif status == "Cancelled":
                print("Update cancelled.", file=sys.stderr)
                sys.exit(1)

            print(f"Update status: {status}, sleeping 5s...")
            time.sleep(5)
        except ClientError as e:
            print(f"Failed to describe update: {e}", file=sys.stderr)
            sys.exit(1)


def update_cluster_access(cluster_name, region, mode, ip_cidr):
    """Update EKS cluster public access CIDRs."""
    try:
        eks = boto3.client("eks", region_name=region)
    except Exception as e:
        print(f"Failed to create EKS client: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching cluster {cluster_name} config...")
    try:
        cluster = eks.describe_cluster(name=cluster_name)
        vpc_config = cluster["cluster"]["resourcesVpcConfig"]
    except ClientError as e:
        print(f"Failed to describe cluster: {e}", file=sys.stderr)
        sys.exit(1)

    # Check if public access is enabled
    if not vpc_config.get("endpointPublicAccess", False):
        print("Cluster public endpoint access is disabled. Cannot add runner IP.", file=sys.stderr)
        sys.exit(1)

    existing_cidrs = vpc_config.get("publicAccessCidrs", [])
    # If explicit CIDRs are not set, AWS defaults to 0.0.0.0/0 (allow all)
    # However, API returns specific list if set.
    # If list is empty or contains 0.0.0.0/0, we might not need to add anything,
    # BUT if we want to RESTRICT access, we'd remove 0.0.0.0/0 and add specific IPs.
    # For this action, we assume we are managing a restricted list.

    # NOTE: If existing_cidrs is ['0.0.0.0/0'], adding a specific IP is redundant but harmless.
    # If we remove an IP and list becomes empty, AWS might revert to default behavioral?
    # Or strict empty list? EKS usually requires at least one CIDR if restricted.

    new_cidrs = set(existing_cidrs)

    if mode == "add":
        print(f"Adding {ip_cidr} to authorized networks...")
        if ip_cidr in new_cidrs:
            print("IP already in authorized networks.")
            return
        new_cidrs.add(ip_cidr)

    elif mode == "remove":
        print(f"Removing {ip_cidr} from authorized networks...")
        if ip_cidr not in new_cidrs:
            print("IP not found in authorized networks, nothing to remove.")
            return
        new_cidrs.remove(ip_cidr)

    if set(existing_cidrs) == new_cidrs:
        print("No changes needed.")
        return

    print("Sending update request...")
    try:
        response = eks.update_cluster_config(
            name=cluster_name, resourcesVpcConfig={"publicAccessCidrs": list(new_cidrs)}
        )
        update_id = response["update"]["id"]
        wait_for_update(eks, cluster_name, update_id)
    except ClientError as e:
        print(f"Failed to update cluster config: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    cluster_name = os.environ.get("INPUT_CLUSTER_NAME")
    region = os.environ.get("INPUT_REGION")
    mode = os.environ.get("INPUT_MODE", "add")
    # Description isn't supported directly in EKS CIDR list like GKE, but we keep the input for consistency

    if not all([cluster_name, region]):
        print("Error: Missing required inputs.", file=sys.stderr)
        sys.exit(1)

    ip = get_public_ip()
    ip_cidr = f"{ip}/32"

    update_cluster_access(cluster_name, region, mode, ip_cidr)


if __name__ == "__main__":
    main()
