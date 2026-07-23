# Integration build: ttl-sh actions vs octopilot

## Current state

- **Core action:** [octopilot](https://github.com/octopilot/actions/tree/main/octopilot) runs `op build --repo <registry> --push`, reads `skaffold.yaml`, builds all artifacts (Dockerfile + Buildpacks), pushes to the given registry, and writes **`build_result.json`** in the workspace with `builds[]` entries (`imageName`, `tag`).
- **Ephemeral integration:** Repos that need short-lived images (e.g. for Kind tests) use three helper actions that push to **ttl.sh** using a UUID from an earlier step:
  - [docker-to-ttl-sh](https://github.com/octopilot/actions/tree/main/docker-to-ttl-sh)
  - [paketo-to-ttl-sh](https://github.com/octopilot/actions/tree/main/paketo-to-ttl-sh)
  - [helm-to-ttl-sh](https://github.com/octopilot/actions/tree/main/helm-to-ttl-sh)

These duplicate the build logic that `op` already implements; they exist so integration jobs can push to ttl.sh (ephemeral) instead of a permanent registry.

## build_result.json contract

Written by `op build --push` (and by the octopilot action). Consumed by promotion, attestation, and deploy steps.

```json
{
  "builds": [
    { "imageName": "my-app", "tag": "ghcr.io/org/my-app:v1.0.0@sha256:..." },
    { "imageName": "my-chart", "tag": "ghcr.io/org/my-chart:v0.1.0@sha256:..." }
  ]
}
```

- **imageName** matches the artifact (from skaffold or op’s convention).
- **tag** is the full reference (registry/image:tag@sha256:digest).

Workflows that use `build_result.json` can resolve images by name, e.g.:

```bash
jq -r '.builds[] | select(.imageName == "cronjob-log-monitor") | .tag' build_result.json
```

## Moving workflows to octopilot + build_result.json

**Benefits:** One build path (op + skaffold), one contract (build_result.json), no separate docker/pack/helm actions.

**Option A – Use octopilot for integration with a ttl.sh-style registry**

- Extend `op build` (or the octopilot action) to support an **ephemeral registry** mode:
  - Input: e.g. `ttl-uuid` (from integration-validate or similar).
  - Behavior: push to `ttl.sh/<ttl-uuid>-<artifact-suffix>:<tag>` instead of `--repo`.
- Then the workflow can:
  1. Run integration-validate (smoke + generate UUID).
  2. Run **octopilot** with `registry: ttl.sh` and `ttl-uuid: ${{ needs.integration-validate.outputs.uuid }}` (or equivalent).
  3. Use **build_result.json** in the deploy job: parse `builds[]` by imageName to get monitor image, cronjob image, chart ref, and pass them to Helm/Kind.

**Option B – Keep ttl-sh actions, align deploy with current outputs**

- Keep using detect-contexts + integration-build-artifact (matrix of docker-to-ttl-sh / paketo-to-ttl-sh / helm-to-ttl-sh).
- Deploy job must consume the artifact outputs (e.g. `image_monitor`, `image_cronjob`, `image_chart`) and derive `chart_ref` / `chart_version` from `image_chart` when the chart was built with pack (OCI image) instead of helm-to-ttl-sh.

## ttl.sh support (implemented)

- **op build (octopilot-pipeline-tools)**  
  Flags `--ttl-uuid` and `--ttl-tag` (default `1h`). When `--ttl-uuid` is set, images are pushed to `ttl.sh/<ttl-uuid>-<suffix>:<ttl-tag>`; suffix is derived from each artifact’s image name (e.g. `cronjob-log-monitor-chart` → `chart`). Writes `build_result.json` as usual.

- **octopilot action**  
  Inputs `ttl-uuid` and `ttl-tag`. When `ttl-uuid` is set, the action passes them to `op build` and does not require `registry`. Use for integration: pass the UUID from `integration-validate.outputs.uuid`.

- **Workflow migration**  
  Replace the matrix of docker-to-ttl-sh / paketo-to-ttl-sh / helm-to-ttl-sh with a single job that runs **octopilot** with `ttl-uuid`. Downstream deploy reads `build_result.json` (e.g. `jq '.builds[] | select(.imageName | endswith("monitor")) | .tag'`) instead of artifact .txt files.

The three ttl-sh actions are **deprecated** in favour of octopilot + ttl-uuid and will be removed once adoption is stable.

## build_result.json is THE contract

`build_result.json` (skaffold's build-artifact schema, written by op on every
build path) is the single per-leg output contract. The key=value
`<output_key>.txt` sidecar is deprecated: the pipeline no longer uploads it,
`integration-build-artifact`'s `output-path` input is retained only for legacy
direct callers, and the write is removed at the next major release together
with the ttl-sh actions. Downstream consumption is `merge-build-results` over
the `integration-*` artifacts, then `jq` by `imageName`.
