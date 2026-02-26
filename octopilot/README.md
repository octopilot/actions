# octopilot/actions/octopilot

Build and push multi-architecture container images using
[Octopilot Pipeline Tools](https://github.com/octopilot/octopilot-pipeline-tools) (`op`).

The action reads `skaffold.yaml` in the workspace, builds all defined artifacts with
Cloud Native Buildpacks and/or Dockerfile builders, assembles OCI manifest lists for
each target platform, pushes everything to the specified registry, and writes a
`build_result.json` contract file that downstream steps (promotion, deployment watch,
attestation) can consume.

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `registry` | No* | — | Target registry and org, e.g. `ghcr.io/octopilot`. *Required unless `ttl-uuid` is set. |
| `ttl-uuid` | No | — | When set, push to **ttl.sh** as `ttl.sh/<ttl-uuid>-<suffix>:<ttl-tag>` and write `build_result.json`. Use for ephemeral integration (e.g. from `integration-validate`). Overrides `registry`. |
| `ttl-tag` | No | `1h` | Tag for ttl.sh when `ttl-uuid` is set. |
| `version` | No | `$GITHUB_REF_NAME` | Version tag applied to pushed images (e.g. `v1.2.3`). |
| `platforms` | No | `linux/amd64` | Comma-separated platform list, e.g. `linux/amd64,linux/arm64`. |
| `op_version` | No | `v1.0.4` | Version of the `ghcr.io/octopilot/op` container image to use in non-bypass mode. |
| `sbom_output` | No | `dist/sbom` | Directory where SBOMs are written. Packaged as `<sbom_output>.tar.gz` when non-empty. |
| `op_binary` | No | `op` | Path to a pre-built `op` binary. Only used when `build_bypass` is `true`. |
| `build_bypass` | No | `false` | Run `op` directly instead of inside a container. Used for bootstrapping or when a pre-built binary is already available (e.g. from a prior `build-binaries` job). |

## Outputs

| Output | Description |
|--------|-------------|
| `digest` | `sha256:…` digest of the last (application) image pushed. Suitable for use with `actions/attest-build-provenance`. |

## Modes

### Container mode (default)

The action pulls `ghcr.io/octopilot/op:<op_version>` and runs `op build` inside it.
Requires Docker-in-Docker (the host Docker socket is mounted into the container).

```yaml
- name: Build and Push
  uses: octopilot/actions/octopilot@main
  with:
    registry: ghcr.io/my-org
    platforms: linux/amd64,linux/arm64
    version: ${{ github.ref_name }}
```

### ttl.sh ephemeral (integration)

For short-lived integration builds (e.g. Kind tests), pass a UUID from an earlier step (e.g. `integration-validate`). Images are pushed to `ttl.sh/<uuid>-<suffix>:<tag>` and `build_result.json` is written for the deploy step.

```yaml
- name: Build and push to ttl.sh
  uses: octopilot/actions/octopilot@main
  with:
    ttl-uuid: ${{ needs.integration-validate.outputs.uuid }}
    ttl-tag: "1h"
    # registry not needed
```

Downstream: use `build_result.json` (e.g. `jq '.builds[] | select(.imageName | endswith("monitor")) | .tag'`) instead of the legacy artifact .txt files.

### Bypass mode

Pass a pre-built `op` binary (e.g. downloaded from a release or produced by a prior job)
and set `build_bypass: true`. The binary runs directly on the runner — no Docker pull
needed for the builder image. Ideal for the self-hosting bootstrap case.

```yaml
- name: Build and Push (bypass)
  uses: octopilot/actions/octopilot@main
  with:
    registry: ghcr.io/my-org
    platforms: linux/amd64,linux/arm64
    version: ${{ github.ref_name }}
    build_bypass: true
    op_binary: ./dist/op-linux-amd64
```

## Full example — tag-triggered release with multi-arch build

```yaml
name: Release

on:
  push:
    tags: ["v*"]

jobs:
  build-binaries:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Build op binaries
        uses: octopilot/actions/build-self-homing@main
        with:
          version: ${{ github.ref_name }}
          output_dir: dist

      - uses: actions/upload-artifact@v4
        with:
          name: dist-binaries
          path: dist/op-*
          retention-days: 1

  build-container:
    needs: build-binaries
    runs-on: ubuntu-latest
    permissions:
      packages: write
      id-token: write
      attestations: write
    steps:
      - uses: actions/checkout@v4

      - name: Download op binary
        uses: actions/download-artifact@v4
        with:
          name: dist-binaries
          path: dist/

      - run: chmod +x dist/op-linux-amd64

      - uses: docker/setup-qemu-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and Push
        id: push
        uses: octopilot/actions/octopilot@main
        with:
          version: ${{ github.ref_name }}
          registry: ghcr.io/${{ github.repository_owner }}
          platforms: linux/amd64,linux/arm64
          sbom_output: dist/sbom
          build_bypass: true
          op_binary: ./dist/op-linux-amd64

      - name: Attest Build Provenance
        uses: actions/attest-build-provenance@v2
        with:
          subject-name: ghcr.io/${{ github.repository_owner }}/op
          subject-digest: ${{ steps.push.outputs.digest }}
          push-to-registry: true
```

## Notes

- **`build_result.json`**: Written to the workspace root after a successful build. Contains
  fully-qualified image references (`imageName` + `tag@sha256:…`) for all built artifacts.
  The `digest` output is taken from the **last** entry (the application image); base images
  appear first by convention.
- **SBOM**: When `sbom_output` is non-empty and SBOMs are generated, the action creates
  `<sbom_output>.tar.gz` automatically.
- **Disk space**: Multi-arch buildpack builds are large. If running on `ubuntu-latest`, consider
  freeing unused toolchains (Android SDK, .NET, etc.) before this action. See
  `octopilot/actions/janitor` or use `just free-disk` from `octopilot-pipeline-tools`.

## Known Gotchas

### Container mode — GHCR `DENIED` on first push (or any private registry)

**Symptom:** Pack's ANALYZE phase fails with:
```
DENIED: requested access to the resource is denied
```
even when `docker/login-action` ran successfully in the same job.

**Cause:** In container mode (`build_bypass: false`), `op build` runs inside
`ghcr.io/octopilot/op`. `docker/login-action` stores credentials in
`~/.docker/config.json` **on the host runner**, but that file is not inside
the container. Pack makes direct HTTPS calls to the registry API (not through
the Docker daemon) during the ANALYZE phase — without the credentials it gets
`DENIED` even for a simple "does this image exist?" check, which GHCR requires
auth for.

**Fix:** This is already handled automatically — the action mounts
`${HOME}/.docker` read-only into the container so Pack finds the same
credentials the host Docker daemon has.

If you see this error it means the action predates the fix. Upgrade to the
latest `octopilot/actions/octopilot@main`.

**Why bypass mode doesn't have this problem:** With `build_bypass: true`, `op`
runs directly on the host runner which already has the credentials. The
container credential mount is not needed.
