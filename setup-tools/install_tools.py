import os
import platform
import stat
import subprocess
import sys
import urllib.request


def download_file(url, dest_path):
    print(f"Downloading {url} to {dest_path}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
    except Exception as e:
        print(f"Failed to download {url}: {e}", file=sys.stderr)
        sys.exit(1)


def make_executable(path):
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IEXEC)


def install_tool(name, version, url_template):
    # Determine architecture
    # Map arch/system to typical release names
    # This is a simplification; real URLs vary by tool.
    # We will handle tool-specific logic below.
    pass


def get_host_info():
    """
    Returns normalized (system, arch) tuple.
    system: linux, darwin
    arch: amd64, arm64, arm
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        system = "darwin"
    elif system == "linux":
        system = "linux"

    # Normalize architecture
    if machine == "x86_64":
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine.startswith("armv7"):
        arch = "arm"
    else:
        # Fallback for other architectures if needed, but for now stick to machine
        arch = machine

    return system, arch


def install_kubectl(version, install_dir):
    system, arch = get_host_info()

    # kubectl uses 'arm' for armv7, 'arm64' for aarch64
    # https://dl.k8s.io/release/v1.29.1/bin/linux/arm64/kubectl
    # https://dl.k8s.io/release/v1.29.1/bin/linux/arm/kubectl

    url = f"https://dl.k8s.io/release/v{version}/bin/{system}/{arch}/kubectl"
    dest = os.path.join(install_dir, "kubectl")

    download_file(url, dest)
    make_executable(dest)
    print(f"Installed kubectl v{version}")


def install_sops(version, install_dir):
    system, arch = get_host_info()

    # sops releases:
    # linux: sops-v3.8.1.linux.amd64
    # darwin: sops-v3.8.1.darwin.amd64
    # arm64: sops-v3.8.1.linux.arm64
    # armv7: sops-v3.8.1.linux.arm

    filename = f"sops-v{version}.{system}.{arch}"
    url = f"https://github.com/getsops/sops/releases/download/v{version}/{filename}"
    dest = os.path.join(install_dir, "sops")

    download_file(url, dest)
    make_executable(dest)
    print(f"Installed sops v{version}")


def install_kustomize(version, install_dir):
    system, arch = get_host_info()

    # kustomize releases:
    # kustomize_v5.3.0_linux_amd64.tar.gz
    # kustomize_v5.3.0_linux_arm64.tar.gz
    # kustomize_v5.3.0_linux_arm.tar.gz
    # kustomize_v5.3.0_darwin_amd64.tar.gz
    # kustomize_v5.3.0_darwin_arm64.tar.gz

    os_name = "darwin" if system == "darwin" else "linux"

    filename = f"kustomize_v{version}_{os_name}_{arch}.tar.gz"
    url = f"https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv{version}/{filename}"
    tar_dest = os.path.join(install_dir, filename)

    download_file(url, tar_dest)

    # Extract
    subprocess.run(["tar", "-xzf", tar_dest, "-C", install_dir], check=True)
    os.remove(tar_dest)
    print(f"Installed kustomize v{version}")


def install_yq(version, install_dir):
    system, arch = get_host_info()

    # yq releases:
    # yq_linux_amd64
    # yq_linux_arm64
    # yq_linux_arm (armv7)
    # yq_darwin_amd64
    # yq_darwin_arm64

    binary_name = f"yq_{system}_{arch}"
    url = f"https://github.com/mikefarah/yq/releases/download/v{version}/{binary_name}"
    dest = os.path.join(install_dir, "yq")

    download_file(url, dest)
    make_executable(dest)
    print(f"Installed yq v{version}")


def main():
    # Use temp dir for install if GITHUB_WORKSPACE is not set (local testing)
    workspace = os.environ.get("GITHUB_WORKSPACE")
    install_dir = os.path.join(workspace, ".bin") if workspace else "/tmp/.bin"  # noqa: S108

    if not os.path.exists(install_dir):
        os.makedirs(install_dir)

    # Add to PATH
    if "GITHUB_PATH" in os.environ:
        with open(os.environ["GITHUB_PATH"], "a") as f:
            f.write(f"{install_dir}\n")
    else:
        print(f"Warning: GITHUB_PATH not set. Binaries installed to {install_dir}")

    versions = {
        "kustomize": os.environ.get("KUSTOMIZE_VERSION", "5.3.0"),
        "sops": os.environ.get("SOPS_VERSION", "3.8.1"),
        "yq": os.environ.get("YQ_VERSION", "4.40.5"),
        "kubectl": os.environ.get("KUBECTL_VERSION", "1.29.1"),
    }

    install_kubectl(versions["kubectl"], install_dir)
    install_sops(versions["sops"], install_dir)
    install_kustomize(versions["kustomize"], install_dir)
    install_yq(versions["yq"], install_dir)


if __name__ == "__main__":
    main()
