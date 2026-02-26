# integration-build-artifact

Builds one integration matrix item (image via **Octopilot**, or Helm chart via helm-to-ttl-sh) and writes key=value output(s) and `build_result.json` for the workflow to upload.

- **Image** (docker or pack): uses [octopilot](../octopilot) with `ttl-uuid` and `artifact` (exact image name from skaffold). Produces `build_result.json` and the step output `tag`; the workflow writes `output_key=<tag>` to the output file.
- **Chart**: uses [helm-to-ttl-sh](../helm-to-ttl-sh) and writes chart ref/version to the output file.

The **integration matrix** is derived by [detect-contexts](../detect-contexts): from `skaffold.yaml` `build.artifacts` (each entry includes `image` for Octopilot’s `--artifact`) and from detect’s `chart_paths`. The receiving job can merge multiple `build_result.json` files with [merge-build-results](../merge-build-results).

**`op_version`** defaults to `v1.0.4` so the Octopilot action uses `ghcr.io/octopilot/op:v1.0.4`. Override to pin a different release (e.g. `v1.0.5`) or use `main` for the latest from the default branch.
