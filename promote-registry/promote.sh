#!/usr/bin/env bash
# Copy the artifacts in a build_result.json from one private registry to another, by digest.
#
#   BUILD_RESULT     build_result.json ({builds: [{imageName, tag: <SRC_REGISTRY>/<path>:<tag>@sha256:...}]})
#   SRC_REGISTRY     registry every build must come from (refs elsewhere, or without a digest, fail)
#   DST_REGISTRY     target registry; an artifact keeps its <path> below the registry
#   VERSION          tag given to images; Helm charts (imageName *-chart) keep their own tag,
#                    which Helm requires to equal the chart version
#   OUTPUT           result file, same contract as build_result.json with the target refs
#   PROMOTE_PARALLEL concurrent copies (default 6)
#
# A target already at the source digest is skipped, so a re-run resumes. A target tag that exists at a
# different digest fails the promotion: tags in an acceptance or production registry never move.
set -euo pipefail

: "${BUILD_RESULT:?}" "${SRC_REGISTRY:?}" "${DST_REGISTRY:?}" "${VERSION:?}" "${OUTPUT:?}"
PROMOTE_PARALLEL="${PROMOTE_PARALLEL:-6}"
SRC_REGISTRY="${SRC_REGISTRY%/}"
DST_REGISTRY="${DST_REGISTRY%/}"

count="$(jq '.builds | length' "$BUILD_RESULT")"
if [ "$count" -eq 0 ]; then
  echo "::error::no builds in $BUILD_RESULT"
  exit 1
fi

PROMOTED_DIR="$(mktemp -d)"
export SRC_REGISTRY DST_REGISTRY VERSION PROMOTED_DIR

promote() {
  local i="$1" name="$2" src="$3" path dst want have
  case "$src" in
    "$SRC_REGISTRY"/*@sha256:*) ;;
    *) echo "::error::$name: $src is not a digest-pinned ref in $SRC_REGISTRY"; return 1 ;;
  esac
  want="${src##*@}"
  path="${src#"$SRC_REGISTRY"/}"
  path="${path%%@*}"
  case "$name" in
    *-chart) dst="${DST_REGISTRY}/${path}" ;;
    *) dst="${DST_REGISTRY}/${path%:*}:${VERSION}" ;;
  esac
  have="$(crane digest "$dst" 2>/dev/null || true)"
  if [ "$have" = "$want" ]; then
    echo "promote: $dst already at $want"
  elif [ -n "$have" ]; then
    echo "::error::$dst exists at $have, the build says $want; promoted tags never move"
    return 1
  else
    echo "promote: $src -> $dst"
    crane cp "$src" "$dst"
    have="$(crane digest "$dst")"
    if [ "$have" != "$want" ]; then
      echo "::error::$dst landed at $have, expected $want"
      return 1
    fi
  fi
  printf '%s\t%s@%s\n' "$name" "$dst" "$have" > "$PROMOTED_DIR/$(printf '%05d' "$i")"
}
export -f promote

jq -r '.builds | to_entries[] | "\(.key)\n\(.value.imageName)\n\(.value.tag)"' "$BUILD_RESULT" \
  | tr '\n' '\0' | xargs -0 -n 3 -P "$PROMOTE_PARALLEL" bash -euo pipefail -c 'promote "$@"' _

# Keep build_result order (file names are the zero-padded build index).
cat "$PROMOTED_DIR"/* \
  | jq -Rn --arg v "$VERSION" '{version: $v, builds: [inputs | split("\t") | {imageName: .[0], tag: .[1]}]}' \
  > "$OUTPUT"
echo "promoted $(jq '.builds | length' "$OUTPUT") artifact(s) to $DST_REGISTRY"
