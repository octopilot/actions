#!/bin/bash
set -e

is_tag="false"
tag=""

# Check GITHUB_REF (CI)
if [[ "$GITHUB_REF" == "refs/tags/"* ]]; then
  echo "GITHUB_REF is a tag."
  is_tag="true"
  tag="${GITHUB_REF#refs/tags/}"
else
  # Fallback to git describe (Local/CI without ref)
  # We need to mark directory as safe for git if running in container
  git config --global --add safe.directory "$GITHUB_WORKSPACE"

  if git describe --exact-match --tags HEAD >/dev/null 2>&1; then
    echo "git describe found a tag."
    is_tag="true"
    tag=$(git describe --exact-match --tags HEAD)
  fi
fi

echo "is_tag=$is_tag" >> $GITHUB_OUTPUT
echo "tag=$tag" >> $GITHUB_OUTPUT
