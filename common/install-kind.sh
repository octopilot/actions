#!/usr/bin/env bash
# install-kind.sh KIND_VERSION KUBECTL_VERSION — put kind and kubectl where helm/kind-action
# looks for them, so its own (retry-less) downloads are skipped.
#
# helm/kind-action@v1 installs into ${RUNNER_TOOL_CACHE}/kind/<kind version>/<arch>/
# {kind,kubectl}/bin/ and only downloads when the binary there is missing. Pre-seeding
# those paths with fetch.sh (retries on 5xx) and the upstream checksums means a GitHub
# release-download outage no longer fails the cluster step. Pass the same versions to
# kind-action (`version`, `kubectl_version`) so the paths and the binaries agree.
set -euo pipefail

kind_version="${1:?usage: install-kind.sh KIND_VERSION KUBECTL_VERSION}"
kubectl_version="${2:?usage: install-kind.sh KIND_VERSION KUBECTL_VERSION}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fetch="$here/fetch.sh"

case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "::error::install-kind: unsupported arch $(uname -m)" >&2; exit 1 ;;
esac
cache="${RUNNER_TOOL_CACHE:?RUNNER_TOOL_CACHE is not set}/kind/${kind_version}/${arch}"

kind_dir="$cache/kind/bin"
if [ -x "$kind_dir/kind" ]; then
  echo "kind ${kind_version} already in the tool cache"
else
  tmp="$(mktemp -d)"
  base="https://github.com/kubernetes-sigs/kind/releases/download/${kind_version}/kind-linux-${arch}"
  bash "$fetch" "$base" "$tmp/kind-linux-${arch}"
  bash "$fetch" "$base.sha256sum" "$tmp/kind.sha256sum"
  (cd "$tmp" && grep "kind-linux-${arch}" kind.sha256sum | sha256sum -c --quiet -)
  mkdir -p "$kind_dir"
  install -m 0755 "$tmp/kind-linux-${arch}" "$kind_dir/kind"
  rm -rf "$tmp"
  echo "kind ${kind_version} installed"
fi

kubectl_dir="$cache/kubectl/bin"
if [ -x "$kubectl_dir/kubectl" ] && "$kubectl_dir/kubectl" version --client 2>/dev/null | grep -q "${kubectl_version}"; then
  echo "kubectl ${kubectl_version} already in the tool cache"
else
  tmp="$(mktemp -d)"
  base="https://dl.k8s.io/release/${kubectl_version}/bin/linux/${arch}/kubectl"
  bash "$fetch" "$base" "$tmp/kubectl"
  bash "$fetch" "$base.sha256" "$tmp/kubectl.sha256"
  echo "$(cat "$tmp/kubectl.sha256")  $tmp/kubectl" | sha256sum -c --quiet -
  mkdir -p "$kubectl_dir"
  install -m 0755 "$tmp/kubectl" "$kubectl_dir/kubectl"
  rm -rf "$tmp"
  echo "kubectl ${kubectl_version} installed"
fi
