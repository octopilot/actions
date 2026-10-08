# Integration registry

Every push builds the repository's artifacts once ("integration artifacts"); the release job promotes those exact
digests on a `v*` tag. By default they go to **ttl.sh**, a public registry with expiring tags, which suits public
repositories. A private repository sets a private registry instead:

```yaml
jobs:
  build:
    permissions:            # the pipeline's jobs request these; a caller that grants less fails at startup
      contents: write
      packages: write
      id-token: write
      pull-requests: write
    uses: octopilot/actions/.github/workflows/pipeline.yml@main
    with:
      integration_registry: us-docker.pkg.dev/<project>/integration
      registry_auth: gcp-wif
      gcp_workload_identity_provider: projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>
      gcp_service_account: <sa>@<project>.iam.gserviceaccount.com
```

- Artifacts land under `<integration_registry>/<repository name, lower-case>/<image>`; `build_result.json` records
  their digests, and the release job promotes from there to GHCR as before.
- `gcp-wif` exchanges the job's GitHub OIDC token for a one-hour Artifact Registry token (Workload Identity
  Federation). No key is stored, and no credentials file is written into the checkout (the build context). The
  service account needs write on the registry. A registry with a cleanup policy (e.g. delete after a day) gives the
  same lifetime as ttl.sh tags.
- `registry_auth` empty: the runner already holds credentials for the registry (e.g. a self-hosted runner with
  ambient cloud credentials).
- The Kind integration deploy (`integration: true`) pulls without registry credentials, so it needs ttl.sh for now;
  the pipeline fails early when both are set.

Because every job declares its permissions, all callers of `pipeline.yml@main` must grant `id-token: write`, also
those that keep ttl.sh.
