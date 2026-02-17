#!/bin/bash
set -e

FALLBACK="${INPUT_FALLBACK:-}"

# Fetch tags (shallow clones might need this)
# Since we are in a container, we might need safe.directory
git config --global --add safe.directory "$GITHUB_WORKSPACE"

# Fetch tags if possible. 
# Note: In some restricted environments fetching might fail if no creds, but usually fine for public or with token.
# We try to fetch tags to ensure we have history.
git fetch --tags --force 2>/dev/null || true

target="HEAD"
# If current commit is a tag, we want the *previous* one, so start searching from parent
if git describe --exact-match --tags HEAD >/dev/null 2>&1; then
  echo "Current commit is a tag. Searching from HEAD^..."
  target="HEAD^"
fi

tag=""
if git describe --tags --abbrev=0 "$target" >/dev/null 2>&1; then
  tag=$(git describe --tags --abbrev=0 "$target")
  echo "Found previous tag: $tag"
else
  echo "No previous tag found."
  tag="$FALLBACK"
fi

echo "tag=$tag" >> $GITHUB_OUTPUT
