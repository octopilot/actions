# integration-build-artifact

Builds one integration matrix item (image or Helm chart) via **Octopilot** and writes key=value output(s) and `build_result.json` for the workflow to upload.

- **Image** (docker or pack): uses [octopilot](../octopilot) with `ttl-uuid` and `artifact` (exact image name from skaffold). Produces `build_result.json` and the step output `tag`; the workflow writes `output_key=<tag>` to the output file.
- **Chart**: uses [octopilot](../octopilot) with `artifact` set to the chart image name (e.g. `ghcr.io/org/myapp-chart`). Requires op v1.0.13+ (chart build uses Docker API, no run image). Produces `build_result.json` with the Helm OCI chart ref.

The **integration matrix** is derived by [detect-contexts](../detect-contexts): from `skaffold.yaml` `build.artifacts` (each entry includes `image` for Octopilot’s `--artifact`) and from detect’s `chart_paths`. The receiving job can merge multiple `build_result.json` files with [merge-build-results](../merge-build-results).

**`op_version`** defaults to `v1.0.13`. Use v1.0.13+ for chart artifacts (no container image for charts). Override to pin a different release.
