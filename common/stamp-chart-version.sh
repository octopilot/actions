#!/usr/bin/env bash
# stamp-chart-version.sh CHART_DIR TAG
#
# Versions a chart from the release tag it is being built for: version is the tag without its leading v (v0.1.1 ->
# 0.1.1) and appVersion the tag itself, the tag the pipeline releases the repository's images under, so the chart's
# default image (.Chart.AppVersion) is the one released with it.
#
# The release pipeline promotes the chart it built to <chart>:TAG. Flux's helm-controller refuses a chart whose
# version differs from its OCI tag ("artifact revision v0.1.1 does not match chart version 0.1.0"), and the release
# only bumps the language's version file, so without this every release after the first ships an undeployable chart.
#
# A tag that is not semver (vX.Y.Z[-pre][+build]) leaves Chart.yaml as written.
set -euo pipefail

dir="${1:?usage: stamp-chart-version.sh CHART_DIR TAG}"
tag="${2:?usage: stamp-chart-version.sh CHART_DIR TAG}"
chart="${dir%/}/Chart.yaml"
[ -f "$chart" ] || { echo "::error::no Chart.yaml in ${dir}" >&2; exit 1; }

version="${tag#v}"
if ! [[ "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
  echo "${tag} is not a semver release tag; ${chart} keeps its version"
  exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
# Only top-level keys (column 0); dependencies[].version is indented and left alone.
awk -v version="$version" -v app="$tag" '
  /^version:/    { print "version: " version; v = 1; next }
  /^appVersion:/ { print "appVersion: \"" app "\""; a = 1; next }
  { print }
  END {
    if (!v) print "version: " version
    if (!a) print "appVersion: \"" app "\""
  }
' "$chart" > "$tmp"
cat "$tmp" > "$chart"
echo "${chart}: version ${version}, appVersion ${tag}"
