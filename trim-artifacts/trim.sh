#!/usr/bin/env bash
# Before this run uploads anything: reduce the repository's Actions artifacts to the newest KEEP of each name.
#
#   KEEP          artifacts left per name (0: do nothing)
#   GITHUB_TOKEN  the workflow token; deleting needs `actions: write` on the job
#   DRY_RUN       non-empty: list what would go, delete nothing
#   MAX_AGE_DAYS  also delete any artifact older than this many days, however few of its name there are (0: no age limit)
#   CLEAR         non-empty: KEEP 0 deletes every artifact (a one-off clear-down) instead of turning trimming off
#   TRIM_REPOSITORY  owner/repo to trim (default: GITHUB_REPOSITORY, the workflow's own)
#
# Artifact storage is one quota per organisation, and a full one fails every upload in every repository. Artifacts of
# this run and of any run still in progress are never deleted (a pipeline downloads in one job what it uploaded in
# another). Trimming is housekeeping: an API failure warns and the run goes ahead.
set -uo pipefail
: "${KEEP:?}" "${GITHUB_TOKEN:?}"
# GITHUB_* variables cannot be overridden in a step, so the target comes in as TRIM_REPOSITORY.
REPO="${TRIM_REPOSITORY:-${GITHUB_REPOSITORY:?}}"
# KEEP 0 is "off" in a pipeline; a deliberate clear-down (CLEAR non-empty) deletes everything instead.
if ! [ "$KEEP" -gt 0 ] 2>/dev/null; then
  if [ "$KEEP" = 0 ] && [ -z "${CLEAR:-}" ] && [ "${MAX_AGE_DAYS:-0}" -gt 0 ] 2>/dev/null; then
    KEEP=1000000          # no count limit: expiry only
  elif ! { [ -n "${CLEAR:-}" ] && [ "$KEEP" = 0 ]; }; then
    echo "trim: keep is ${KEEP}; nothing trimmed"; exit 0
  fi
fi
API="${GITHUB_API_URL:-https://api.github.com}/repos/${REPO}"
gh_api() { curl -fsS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$@"; }
# DELETE returning only the HTTP status (204 deleted, 403 the token may not delete, anything else a failure).
gh_delete() { curl -sS -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$1" 2>/dev/null || echo 000; }

all='[]'; page=1
while :; do
  json="$(gh_api "${API}/actions/artifacts?per_page=100&page=${page}" 2>&1)" || {
    echo "::warning::trim: listing artifacts failed (${json:0:200}); nothing deleted"; exit 0; }
  n="$(jq '.artifacts | length' <<<"$json")"
  all="$(jq -c --argjson acc "$all" '$acc + [.artifacts[] | select(.expired | not)
          | {id, name, size_in_bytes, created_at, run: (.workflow_run.id // 0)}]' <<<"$json")"
  [ "$n" -eq 100 ] || break
  page=$((page+1))
done

# Candidates: beyond the newest KEEP of their name, or older than MAX_AGE_DAYS (expired); never this run's.
MAX_AGE_DAYS="${MAX_AGE_DAYS:-0}"
[ "$MAX_AGE_DAYS" -ge 0 ] 2>/dev/null || MAX_AGE_DAYS=0
cutoff=""
[ "$MAX_AGE_DAYS" -eq 0 ] || cutoff="$(date -u -d "-${MAX_AGE_DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-"${MAX_AGE_DAYS}"d +%Y-%m-%dT%H:%M:%SZ)"
candidates="$(jq -c --argjson keep "$KEEP" --arg cutoff "$cutoff" --argjson self "$([ "$REPO" = "${GITHUB_REPOSITORY:-}" ] && echo "${GITHUB_RUN_ID:-0}" || echo 0)" '
  group_by(.name) | map(sort_by(.created_at) | reverse | to_entries | map(select(.key >= $keep or ($cutoff != "" and .value.created_at < $cutoff)) | .value))
  | add // [] | map(select(.run != $self))' <<<"$all")"
echo "trim: ${REPO}: $(jq length <<<"$all") artifacts, $(jq length <<<"$candidates") beyond the newest ${KEEP} of each name${cutoff:+ or created before ${cutoff}}"

declare -A live=()
deleted=0; freed=0; held=0; failed=0; denied=0
while IFS=$'\t' read -r id name size run; do
  [ -n "$id" ] || continue
  if [ "$run" != 0 ] && [ -z "${live[$run]+x}" ]; then
    status="$(gh_api "${API}/actions/runs/${run}" 2>/dev/null | jq -r '.status // "completed"')" || status="unknown"
    live[$run]=$([ "$status" = completed ] && echo 0 || echo 1)
  fi
  if [ "${live[$run]:-0}" = 1 ]; then held=$((held+1)); continue; fi
  if [ -n "${DRY_RUN:-}" ]; then echo "trim (dry run): would delete ${name} #${id}"; deleted=$((deleted+1)); freed=$((freed+size)); continue; fi
  code="$(gh_delete "${API}/actions/artifacts/${id}")"
  case "$code" in
    2??) deleted=$((deleted+1)); freed=$((freed+size)) ;;
    # The token cannot delete (no actions: write): every further call would be refused too, and each costs a round
    # trip (915 of them ran BRRTRouter's Detect job past its 10-minute limit on 27 Oct). Stop at the first one.
    403) denied=1; break ;;
    *) failed=$((failed+1)) ;;
  esac
done < <(jq -r '.[] | "\(.id)\t\(.name)\t\(.size_in_bytes)\t\(.run)"' <<<"$candidates")

[ "$denied" -eq 0 ] || echo "::warning::trim: deleting is refused (HTTP 403): give the calling job actions: write; nothing more tried"
[ "$failed" -eq 0 ] || echo "::warning::trim: ${failed} artifact(s) could not be deleted"
verb="deleted"; [ -z "${DRY_RUN:-}" ] || verb="would delete (dry run)"
msg="kept the newest ${KEEP} of each artifact name${cutoff:+ younger than ${MAX_AGE_DAYS} days}; ${verb} ${deleted} ($((freed / 1048576)) MiB)"
[ "$held" -eq 0 ] || msg="${msg}, ${held} left for runs still going"
echo "trim: ${REPO}: ${msg}"
{ echo "### Artifact trim: ${REPO}"; echo; echo "${msg^}."; } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit 0
