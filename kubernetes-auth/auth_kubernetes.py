import base64
import json
import os
import sys
import tempfile
import time
from urllib.parse import urlparse

import requests


def get_oidc_token(oidc_url, username, password):
    """Fetch OIDC token using Resource Owner Password Credentials flow."""
    print(f"Fetching OIDC token from {oidc_url}...")

    # Basic Auth header: base64(username:password)
    auth_str = f"{username}:{password}"
    auth_bytes = auth_str.encode("ascii")
    auth_b64 = base64.b64encode(auth_bytes).decode("ascii")

    headers = {"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"}

    # The original implementation appends client_id to the body,
    # effectively using it as both Basic Auth user AND client_id param?
    # Replicating original logic:
    # newSearchParams.append("client_id", oidcUsername);
    data = {"client_id": username}

    try:
        response = requests.post(oidc_url, headers=headers, data=data, timeout=10)
        response.raise_for_status()

        token_data = response.json()
        token = token_data.get("access_token")

        if not token:
            print("Error: No access_token in OIDC response", file=sys.stderr)
            sys.exit(1)

        return token

    except Exception as e:
        print(f"Failed to get OIDC token: {e}", file=sys.stderr)
        if "response" in locals() and response is not None:
            print(f"Response: {response.text}", file=sys.stderr)
        sys.exit(1)


def create_kubeconfig(token, oidc_url, username, k8s_url, namespace, skip_tls):
    """Generate and save kubeconfig file."""

    # Original implementation uses oidcUrl.origin for idp-issuer-url
    # We'll just use the provided URL's origin roughly, or pass the full URL if that matches logic.
    # The TS code used `oidcUrl.origin`. In Python:
    parsed_oidc = urlparse(oidc_url)
    issuer_url = f"{parsed_oidc.scheme}://{parsed_oidc.netloc}"

    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": "default-cluster",
                "cluster": {
                    "insecure-skip-tls-verify": skip_tls,
                    "server": k8s_url,
                },
            },
        ],
        "users": [
            {
                "name": "default-user",
                "user": {
                    "auth-provider": {
                        "config": {
                            "client-id": username,
                            "id-token": token,
                            "idp-issuer-url": issuer_url,
                        },
                        "name": "oidc",
                    },
                },
            },
        ],
        "contexts": [
            {
                "context": {
                    "cluster": "default-cluster",
                    "namespace": namespace,
                    "user": "default-user",
                },
                "name": "default-context",
            },
        ],
        "current-context": "default-context",
    }

    # Create temp directory logic similar to original
    # runnerTempDirectory = process.env.RUNNER_TEMP || "/tmp/";
    runner_temp = os.environ.get("RUNNER_TEMP", tempfile.gettempdir())
    config_dir = os.path.join(runner_temp, f"kube_config_{int(time.time())}")
    os.makedirs(config_dir, exist_ok=True)

    config_path = os.path.join(config_dir, "custom-config")

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"Kubeconfig created at {config_path}")
    return config_path


def main():
    oidc_url = os.environ.get("INPUT_OIDC_URL")
    username = os.environ.get("INPUT_OIDC_USERNAME")
    password = os.environ.get("INPUT_OIDC_PASSWORD")
    k8s_url = os.environ.get("INPUT_K8S_URL")
    namespace = os.environ.get("INPUT_K8S_NAMESPACE", "default")
    skip_tls_str = os.environ.get("INPUT_K8S_SKIP_TLS_VERIFY", "false")

    skip_tls = skip_tls_str.lower() == "true"

    if not all([oidc_url, username, password, k8s_url]):
        print("Error: Missing required inputs.", file=sys.stderr)
        sys.exit(1)

    # 1. Get Token
    token = get_oidc_token(oidc_url, username, password)

    # Mask token in logs (Github Actions)
    print(f"::add-mask::{token}")

    # 2. Create Kubeconfig
    config_path = create_kubeconfig(token, oidc_url, username, k8s_url, namespace, skip_tls)

    # 3. Export KUBECONFIG
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write(f"KUBECONFIG={config_path}\n")
    else:
        print(f"Export KUBECONFIG={config_path}")


if __name__ == "__main__":
    main()
