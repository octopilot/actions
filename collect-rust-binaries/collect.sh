#!/usr/bin/env bash
# Collect top-level Cargo debug/release binaries (and shared libs) into
# build_artifacts/{debug,release}/. Skips deps/, build/, incremental/, and
# compiler sidecars (*.d, *.rlib, *.rmeta).
#
# Usage: collect.sh [TARGET_DIR] [OUT_DIR]
# Defaults: ${CARGO_TARGET_DIR:-target}  and  ${GITHUB_WORKSPACE:-.}/build_artifacts
set -euo pipefail

TARGET_DIR="${1:-${CARGO_TARGET_DIR:-target}}"
OUT_DIR="${2:-${GITHUB_WORKSPACE:+$GITHUB_WORKSPACE/build_artifacts}}"
OUT_DIR="${OUT_DIR:-build_artifacts}"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "No Cargo target dir at $TARGET_DIR — nothing to collect"
  mkdir -p "$OUT_DIR"
  exit 0
fi

mkdir -p "$OUT_DIR"
# Default: replace profile dirs. Set COLLECT_APPEND=1 to merge from multiple
# target trees (e.g. lint over several rust workdirs).
if [[ "${COLLECT_APPEND:-0}" != "1" ]]; then
  rm -rf "${OUT_DIR}/debug" "${OUT_DIR}/release"
  : >"${OUT_DIR}/manifest.txt"
fi

collected=0
manifest="${OUT_DIR}/manifest.txt"
touch "$manifest"

is_collectible() {
  local f="$1" base
  base="$(basename "$f")"
  case "$base" in
    *.d|*.rlib|*.rmeta|*.timestamp|*.stamp) return 1 ;;
    # BRRTRouter/codegen companion crates (*_gen) — not shippable app binaries.
    *_gen) return 1 ;;
  esac
  # Top-level Cargo outputs are either executables or shared/static libs.
  if [[ -x "$f" ]]; then
    return 0
  fi
  case "$base" in
    *.so|*.dylib|*.dll|*.a) return 0 ;;
  esac
  return 1
}

for profile in debug release; do
  src="${TARGET_DIR}/${profile}"
  [[ -d "$src" ]] || continue
  dest="${OUT_DIR}/${profile}"
  mkdir -p "$dest"
  # Only direct children — never walk deps/examples/build/incremental.
  while IFS= read -r -d '' f; do
    if is_collectible "$f"; then
      cp -a "$f" "$dest/"
      base="$(basename "$f")"
      size="$(wc -c <"$f" | tr -d ' ')"
      if command -v sha256sum >/dev/null 2>&1; then
        sum="$(sha256sum "$f" | awk '{print $1}')"
      else
        sum="nosha"
      fi
      # Append mode: drop any stale manifest line for this file first.
      if [[ "${COLLECT_APPEND:-0}" == "1" ]] && grep -q "^${profile}/${base}  " "$manifest" 2>/dev/null; then
        grep -v "^${profile}/${base}  " "$manifest" > "${manifest}.tmp" && mv "${manifest}.tmp" "$manifest"
      fi
      echo "${profile}/${base}  size=${size}  sha256=${sum}" | tee -a "$manifest"
      collected=$((collected + 1))
    fi
  done < <(find "$src" -maxdepth 1 -type f -print0 2>/dev/null)
done

echo "Collected ${collected} artifact(s) into ${OUT_DIR}"
if [[ "$collected" -gt 0 ]]; then
  ls -la "$OUT_DIR"/debug "$OUT_DIR"/release 2>/dev/null || true
fi
