# Image sources

Every image the pipeline and the actions pull has a default written in the action: `ghcr.io/octopilot/op`, the
action images under `ghcr.io/octopilot/actions/*`, `kindest/node`, `hello-world`, and (inside `op`) the buildpack
builders and run images named in `skaffold.yaml` or in a builder's metadata.

Set `image_registry` and all of them are pulled from that registry instead, with their repository path unchanged.
Leave it empty and nothing changes.

```yaml
jobs:
  build:
    uses: octopilot/actions/.github/workflows/pipeline.yml@v1
    secrets: inherit
    with:
      runner: pw-gcp
      image_registry: us-docker.pkg.dev/pw-ctl/ci
```

| Written in the action | Pulled with `image_registry: us-docker.pkg.dev/pw-ctl/ci` |
| --- | --- |
| `ghcr.io/octopilot/op:v1.2.0` | `us-docker.pkg.dev/pw-ctl/ci/octopilot/op:v1.2.0` |
| `ghcr.io/octopilot/actions/release:latest` | `us-docker.pkg.dev/pw-ctl/ci/octopilot/actions/release:latest` |
| `kindest/node:v1.34.3` | `us-docker.pkg.dev/pw-ctl/ci/kindest/node:v1.34.3` |
| `hello-world:latest` | `us-docker.pkg.dev/pw-ctl/ci/library/hello-world:latest` |
| `ghcr.io/octopilot/builder-jammy-base:<tag>` (skaffold `builder`) | `us-docker.pkg.dev/pw-ctl/ci/octopilot/builder-jammy-base:<tag>` |

That layout is what a pull-through mirror serves: an Artifact Registry virtual repository whose upstreams are remote
repositories for ghcr.io, Docker Hub, quay.io and registry.k8s.io resolves the upstream path against each of them.
A registry that does not keep upstream paths will not work.

## How it reaches each image

- **Reusable workflows** (`pipeline.yml`, `integration-artifacts-wave.yml`) take `image_registry`, set it as
  `OCTOPILOT_IMAGE_REGISTRY` for every job, and pass it to each octopilot action they call.
- **Composite actions** take `image_registry`; when it is empty they read `OCTOPILOT_IMAGE_REGISTRY`, so a workflow can
  set it once at job or workflow level. Nested actions receive it explicitly.
- **The runner** can declare its own mirror: `OCTOPILOT_RUNNER_IMAGE_REGISTRY` in the runner's environment (e.g. on
  self-hosted runner pods next to an Artifact Registry) is used when neither the input nor the workflow sets one, so every
  job on those runners pulls through it with no workflow change.
- **Action images** (`bump-version`, `kubernetes-auth`, `read-properties`, `release`, `rotate-secret`,
  `sops-decrypt`) are composite actions that run their image with `common/run-action-image.sh`, the way the runner runs a
  `using: docker` action (workspace at `/github/workspace`, `INPUT_*`/`GITHUB_*` passed, outputs and exported variables
  written back). A docker action's `image:` is fixed in its metadata and could not be redirected. `image_tag` selects
  a tag other than `latest`.
- **op** receives it as `OP_IMAGE_REGISTRY` (`op build --image-registry`) and pulls buildpack builders and run images
  through it. Images the skaffold config builds itself, and local/ephemeral registries (localhost, ttl.sh), are never
  rewritten. A Dockerfile can opt in with `ARG OP_IMAGE_REGISTRY=docker.io` and `FROM ${OP_IMAGE_REGISTRY}/library/...`.

The rule lives in one place for the actions, `common/resolve-image.sh` (also exposed as the `resolve-image` action), and
mirrors `op`'s in Go.

## Authentication

Pulling from a private registry is the runner's job: the docker daemon gets credentials from the runner's docker
config. On a self-hosted runner on GKE that is `docker-credential-gcr` with Workload Identity; on GitHub-hosted
runners, log in first (e.g. `google-github-actions/auth` then `gcloud auth configure-docker`). Inside the op
container, where credential helpers do not exist, `op` falls back to Google credentials (Workload Identity, metadata
server, `GOOGLE_APPLICATION_CREDENTIALS`) for `gcr.io` and `*.pkg.dev`.
