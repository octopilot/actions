#!/usr/bin/env bash
# resolve-image.sh REF [REGISTRY]
#
# Prints the reference to pull for REF. With no registry (REGISTRY, else $OCTOPILOT_IMAGE_REGISTRY), REF is printed as
# written: the value in the action is the default. With a registry, typically a pull-through mirror such as an Artifact
# Registry virtual repository, REF's registry is replaced and its repository path kept; the same rule as
# `op build --image-registry`:
#
#   ghcr.io/octopilot/op:v1.2.0   ->  <registry>/octopilot/op:v1.2.0
#   kindest/node:v1.34.3          ->  <registry>/kindest/node:v1.34.3
#   hello-world:latest            ->  <registry>/library/hello-world:latest
#
# Local and ephemeral registries (localhost, 127.0.0.1, host.docker.internal, ttl.sh) and references already on the
# registry's host are printed unchanged.
set -euo pipefail

ref="${1:?usage: resolve-image.sh REF [REGISTRY]}"
if [ "$#" -ge 2 ]; then registry="$2"; else registry="${OCTOPILOT_IMAGE_REGISTRY:-}"; fi
registry="${registry%/}"

if [ -z "$registry" ]; then
  printf '%s\n' "$ref"
  exit 0
fi

first="${ref%%/*}"
if [ "$first" != "$ref" ] && { [[ "$first" == *.* ]] || [[ "$first" == *:* ]] || [ "$first" = localhost ]; }; then
  host="$first"
  path="${ref#*/}"
else
  host="docker.io"
  path="$ref"
fi
host="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"

case "$host" in
  docker.io | index.docker.io | registry-1.docker.io)
    # Docker Hub official images live under library/
    [[ "$path" == */* ]] || path="library/${path}"
    ;;
  localhost | localhost:* | 127.0.0.1 | 127.0.0.1:* | host.docker.internal | host.docker.internal:* | ttl.sh)
    printf '%s\n' "$ref"
    exit 0
    ;;
esac

if [ "$host" = "${registry%%/*}" ]; then
  printf '%s\n' "$ref"
  exit 0
fi

printf '%s/%s\n' "$registry" "$path"
