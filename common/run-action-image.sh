#!/usr/bin/env bash
# run-action-image.sh IMAGE_PATH
#
# Runs one of this repository's action images (ghcr.io/IMAGE_PATH, e.g. octopilot/actions/read-properties) the way the
# runner runs a `using: docker` action, so the image can come from a configurable registry. A docker action's
# `image: docker://...` is fixed in its metadata; a composite action calling this script is not:
#
#   OCTOPILOT_IMAGE_REGISTRY    registry to pull from, keeping the path (see resolve-image.sh); default
#                               $OCTOPILOT_RUNNER_IMAGE_REGISTRY (the runner's own mirror), else ghcr.io
#   OCTOPILOT_ACTION_IMAGE_TAG  image tag; default latest
#   OCTOPILOT_PASS_ENV          extra variable names to pass into the container (e.g. API keys)
#
# Like the runner: the workspace is mounted at /github/workspace (the working directory, and GITHUB_WORKSPACE inside),
# GITHUB_* / RUNNER_* / ACTIONS_* / INPUT_* and CI are passed through, and the file-command files (GITHUB_OUTPUT,
# GITHUB_ENV, ...) are mounted at their own paths so outputs and exported variables reach the job.
set -euo pipefail

path="${1:?usage: run-action-image.sh IMAGE_PATH}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
image="$("$here/resolve-image.sh" "ghcr.io/${path}:${OCTOPILOT_ACTION_IMAGE_TAG:-latest}")"
echo "Action image: ${image}"

env_args=()
for name in $(compgen -e); do
  case "$name" in
    GITHUB_WORKSPACE) ;;
    GITHUB_* | RUNNER_* | ACTIONS_* | INPUT_* | CI) env_args+=(-e "$name") ;;
  esac
done
for name in ${OCTOPILOT_PASS_ENV:-}; do
  if [ -n "${!name+set}" ]; then env_args+=(-e "$name"); fi
done

mounts=(-v "${GITHUB_WORKSPACE:-$PWD}:/github/workspace")
declare -A mounted=()
for var in RUNNER_TEMP GITHUB_OUTPUT GITHUB_ENV GITHUB_PATH GITHUB_STEP_SUMMARY GITHUB_STATE; do
  value="${!var:-}"
  [ -n "$value" ] || continue
  dir="$value"
  [ "$var" = RUNNER_TEMP ] || dir="$(dirname "$value")"
  [ -n "${mounted[$dir]:-}" ] && continue
  under=""
  for m in "${!mounted[@]}"; do
    case "$dir/" in "$m/"*) under=1 ;; esac
  done
  [ -n "$under" ] && continue
  mounted[$dir]=1
  mounts+=(-v "${dir}:${dir}")
done

exec docker run --rm --pull always \
  "${mounts[@]}" \
  -w /github/workspace \
  "${env_args[@]}" \
  -e GITHUB_WORKSPACE=/github/workspace \
  "$image"
