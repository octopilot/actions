# integration-build-artifact

Builds one integration matrix item (image via docker or pack, or Helm chart) and writes key=value output(s) for the workflow to upload.

The **integration matrix** is derived by [detect-contexts](../detect-contexts): from `skaffold.yaml` `build.artifacts` (build method is **docker** if a `Dockerfile` exists in the artifact context, otherwise **pack**) and from detect’s `chart_paths`. No hardcoded artifact names in the workflow.
