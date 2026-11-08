#!/usr/bin/env bash
# fetch.sh URL OUT — download URL to OUT, retrying transient failures.
#
# GitHub release downloads (github.com/<owner>/<repo>/releases/download/...) and other
# tool hosts intermittently answer 5xx (2026-11-08: GitHub's edge returned 504 Gateway
# Time-out for kind, nextest and sccache release assets for ~an hour while githubstatus
# showed green). A single `curl | tar` turns that into a failed release build. This
# retries 5xx / 408 / 429 / connection errors / timeouts with backoff, writes to
# OUT.part and renames on success (no half-written file on failure), and stops at once
# on any other 4xx (wrong URL or version: retrying will not help).
#
# Env: FETCH_ATTEMPTS (default 6), FETCH_MAX_TIME seconds per attempt (default 300).
# Exit: 0 on success, 1 when every attempt failed or the server answered a hard 4xx.
set -uo pipefail

url="${1:?usage: fetch.sh URL OUT}"
out="${2:?usage: fetch.sh URL OUT}"
attempts="${FETCH_ATTEMPTS:-6}"
max_time="${FETCH_MAX_TIME:-300}"

mkdir -p "$(dirname "$out")"
for i in $(seq 1 "$attempts"); do
  code="$(curl --proto '=https' --tlsv1.2 -sSL --connect-timeout 20 --max-time "$max_time" \
    -o "$out.part" -w '%{http_code}' "$url")"
  rc=$?
  if [ "$rc" -eq 0 ] && [ "${code:-000}" -ge 200 ] && [ "${code:-000}" -lt 300 ]; then
    mv -f "$out.part" "$out"
    exit 0
  fi
  rm -f "$out.part"
  case "${code:-000}" in
    4??)
      if [ "$code" != 408 ] && [ "$code" != 429 ]; then
        echo "::error::fetch: HTTP $code for $url (not retryable)" >&2
        exit 1
      fi
      ;;
  esac
  if [ "$i" -lt "$attempts" ]; then
    delay=$((i * i * 3))
    echo "::warning::fetch: attempt $i/$attempts got HTTP ${code:-000} (curl exit $rc) for $url; retrying in ${delay}s" >&2
    sleep "$delay"
  fi
done
echo "::error::fetch: giving up on $url after $attempts attempts (last: HTTP ${code:-000}, curl exit $rc)" >&2
exit 1
