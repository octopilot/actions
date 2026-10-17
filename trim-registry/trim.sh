#!/usr/bin/env bash
# Before a push: reduce each artifact's versions in the target registry to KEEP, counting the one about to be pushed.
#
#   BUILD_RESULT   build_result.json ({builds: [{imageName, tag: <src>/<path>:<tag>@sha256:...}]})
#   SRC_REGISTRY   registry the build refs are under (the artifact's path below it is its path in the target)
#   DST_REGISTRY   target: <loc>-docker.pkg.dev/<project>/<repository>[/prefix] (Artifact Registry) or ghcr.io/<owner>
#   KEEP           versions left per artifact after the push (0: do nothing)
#   ACCESS_TOKEN   Artifact Registry: OAuth token of an identity with artifactregistry.versions.delete
#   GITHUB_TOKEN   ghcr.io: the workflow token (packages: write; the repository needs Admin on the package)
#   DRY_RUN        non-empty: list what would go, delete nothing
#
# Versions are ranked by their highest vX.Y.Z tag, then by update time; untagged ones rank lowest. The digest being
# pushed is never deleted, and neither is anything when a listing fails: trimming is housekeeping, a failure warns and
# the push goes ahead.
set -uo pipefail
: "${BUILD_RESULT:?}" "${DST_REGISTRY:?}" "${KEEP:?}"
[ "$KEEP" -gt 0 ] 2>/dev/null || { echo "trim: keep is ${KEEP}; nothing trimmed"; exit 0; }
SRC_REGISTRY="${SRC_REGISTRY%/}"
DST_REGISTRY="${DST_REGISTRY%/}"

# jq: the rank of a version from its tag names, highest semver first; [-1,-1,-1] when it has none.
RANK='def semver: capture("^v?(?<a>[0-9]+)\\.(?<b>[0-9]+)\\.(?<c>[0-9]+)$") | [(.a|tonumber),(.b|tonumber),(.c|tonumber)];
      def rank($tags): ([$tags[] | (semver? // empty)] | max) // [-1,-1,-1];'

deleted=0; failed=0

# One artifact: $1 = path below the registry (no tag), $2 = digest being pushed.
trim_gar() {
  local path="$1" want="$2" host project repo prefix loc pkg base url page json versions victims
  host="${DST_REGISTRY%%/*}"
  loc="${host%-docker.pkg.dev}"
  IFS=/ read -r project repo prefix <<<"${DST_REGISTRY#*/}"
  [ -n "$prefix" ] && path="${prefix}/${path}"
  pkg="$(jq -rn --arg p "$path" '$p | @uri')"
  base="https://artifactregistry.googleapis.com/v1/projects/${project}/locations/${loc}/repositories/${repo}/packages/${pkg}/versions"
  versions='[]'; page=""
  while :; do
    url="${base}?view=FULL&pageSize=500${page:+&pageToken=${page}}"
    json="$(curl -fsS -H "Authorization: Bearer ${ACCESS_TOKEN}" "$url" 2>&1)" || {
      if echo "$json" | grep -q " 404"; then echo "trim: ${path}: not in ${DST_REGISTRY} yet"; return 0; fi
      echo "::warning::trim: listing ${path} failed (${json:0:200}); nothing deleted"; failed=$((failed+1)); return 0; }
    versions="$(jq -c --argjson acc "$versions" '$acc + (.versions // [])' <<<"$json")"
    page="$(jq -r '.nextPageToken // empty' <<<"$json")"
    [ -n "$page" ] || break
  done
  victims="$(jq -r --arg want "$want" --argjson keep "$KEEP" "$RANK"'
    [ .[] | {name, digest: (.name | split("/") | last), t: (.updateTime // .createTime // ""),
             tags: [(.relatedTags // [])[] | .name | split("/") | last]} ]
    | map(. + {r: rank(.tags)})
    | [ .[] | select(.digest != $want) ] | sort_by([.r, .t]) | reverse
    | .[($keep - 1):][] | "\(.name)\t\(.tags | join(","))"' <<<"$versions")"
  while IFS=$'\t' read -r name tags; do
    [ -n "$name" ] || continue
    if [ -n "${DRY_RUN:-}" ]; then echo "trim (dry run): ${path}: would delete ${name##*/} (${tags:-untagged})"; deleted=$((deleted+1)); continue; fi
    if curl -fsS -X DELETE -H "Authorization: Bearer ${ACCESS_TOKEN}" "https://artifactregistry.googleapis.com/v1/${name}?force=true" >/dev/null; then
      echo "trim: ${path}: deleted ${name##*/} (${tags:-untagged})"; deleted=$((deleted+1))
    else
      echo "::warning::trim: ${path}: could not delete ${name##*/}"; failed=$((failed+1))
    fi
  done <<<"$victims"
}

trim_ghcr() {
  local base="$1" want="$2" owner kind json victims
  owner="${DST_REGISTRY#ghcr.io/}"; owner="${owner%%/*}"
  for kind in orgs users; do
    json="$(curl -fsS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
      "https://api.github.com/${kind}/${owner}/packages/container/$(jq -rn --arg p "$base" '$p|@uri')/versions?per_page=100" 2>/dev/null)" && break
  done
  [ -n "$json" ] || { echo "trim: ghcr.io/${owner}/${base}: no package yet, or not visible to this token"; return 0; }
  victims="$(jq -r --arg want "$want" --argjson keep "$KEEP" "$RANK"'
    [ .[] | {id, digest: .name, t: (.updated_at // .created_at), tags: (.metadata.container.tags // [])} ]
    | map(. + {r: rank(.tags)}) | [ .[] | select(.digest != $want) ] | sort_by([.r, .t]) | reverse
    | .[($keep - 1):][] | "\(.id)\t\(.digest)\t\(.tags | join(","))"' <<<"$json")"
  while IFS=$'\t' read -r id digest tags; do
    [ -n "$id" ] || continue
    if [ -n "${DRY_RUN:-}" ]; then echo "trim (dry run): ghcr.io/${owner}/${base}: would delete ${digest} (${tags:-untagged})"; deleted=$((deleted+1)); continue; fi
    if curl -fsS -X DELETE -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
        "https://api.github.com/${kind}/${owner}/packages/container/$(jq -rn --arg p "$base" '$p|@uri')/versions/${id}" >/dev/null; then
      echo "trim: ghcr.io/${owner}/${base}: deleted ${digest} (${tags:-untagged})"; deleted=$((deleted+1))
    else
      echo "::warning::trim: ghcr.io/${owner}/${base}: could not delete ${digest} (the repository needs Admin on the package)"; failed=$((failed+1))
    fi
  done <<<"$victims"
}

while IFS=$'\t' read -r name src; do
  want=""; case "$src" in *@sha256:*) want="${src##*@}" ;; esac
  ref="${src%%@*}"
  case "$DST_REGISTRY" in
    ghcr.io/*)
      base="$(basename "${name%%:*}")"
      trim_ghcr "$base" "$want" ;;
    *-docker.pkg.dev/*)
      : "${ACCESS_TOKEN:?an Artifact Registry target needs access-token}"
      path="${ref#"$SRC_REGISTRY"/}"
      path="${path%:*}"
      trim_gar "$path" "$want" ;;
    *) echo "::warning::trim: ${DST_REGISTRY} is neither Artifact Registry nor ghcr.io; not trimmed"; exit 0 ;;
  esac
done < <(jq -r '.builds[] | "\(.imageName)\t\(.tag)"' "$BUILD_RESULT")

note=""; [ "$failed" -eq 0 ] || note=" (${failed} warning(s))"
verb="deleted"; [ -z "${DRY_RUN:-}" ] || verb="would be deleted (dry run)"
echo "trim: ${deleted} version(s) ${verb}, keeping ${KEEP} per artifact in ${DST_REGISTRY}${note}"
{
  echo "### Registry trim: \`${DST_REGISTRY}\`"
  echo
  echo "Kept the newest ${KEEP} versions of each artifact (counting this push); deleted ${deleted}."
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit 0
