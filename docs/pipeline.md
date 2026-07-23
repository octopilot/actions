# Octopilot Pipeline — reusable CI/CD in ~5 lines

The **Octopilot Pipeline** (`octopilot/actions/.github/workflows/pipeline.yml`) is
a single reusable GitHub Actions workflow that gives any repository the full
Octopilot build → test → integration DAG, auto-shaped to that repo. A repository
adopts it with a tiny caller; everything else — languages, service count, chart,
deploy — is discovered at runtime.

```yaml
# .github/workflows/octopilot-ci.yml
name: Octopilot CI
on:
  push: { branches: [main], tags: ["v*"] }
  pull_request: { branches: [main] }
  workflow_dispatch:

jobs:
  build:
    name: Octopilot
    uses: octopilot/actions/.github/workflows/pipeline.yml@v1
    with:
      integration: true          # opt in to the Kind + Flux deploy (see below)
    secrets: inherit
```

That's the whole workflow. The jobs render nested under the `Octopilot` node in
the Actions graph (`Octopilot / Detect Contexts`, `Octopilot / Test`, …).

## What you get

The pipeline is driven entirely by `detect-contexts`, which reads `skaffold.yaml`
as the source of truth for the application shape:

| Stage | What it does |
| --- | --- |
| **Detect Contexts** | Parses `skaffold.yaml` → languages, versions, build matrix, chart paths, integration matrix. |
| **Lint** | Language-aware pre-commit / fmt / clippy, per detected context. |
| **Test** (matrix) | Runs tests per language context with coverage. |
| **Integration (validate)** | Release build gate + a UUID for ephemeral artifacts. |
| **Integration (artifacts)** (matrix) | Builds & pushes each service image (buildpack or Dockerfile) and the Helm chart to **ttl.sh**. |
| **Integration (deploy)** | *(opt-in)* Stands the app up in Kind via a Flux `HelmRelease` and runs the chart's Helm tests. |
| **Release (publish)** | *(tags only)* Promotes the run's tested ttl.sh artifacts **by digest** to `ghcr.io/<owner>/<basename>:<tag>`, uploads `release-build-result` (the released refs, `build_result.json` contract), and creates a GitHub Release — AI notes with `ANTHROPIC_API_KEY`, GitHub-generated notes otherwise — with any binary deliverable dists attached. |

The topology is invariant across repos — only the matrices change — so the DAG
always looks the same and the workflow never needs to know your languages.

## Fork-safe by construction

- Integration images and charts go to **ttl.sh** (anonymous, namespace-free), so
  a fork's PR builds and pushes in the fork's own space with **no upstream
  credentials**.
- Permanent images use `ghcr.io/${{ github.repository_owner }}/…`, which on a
  fork resolves to the fork owner.
- `secrets: inherit` runs secret-dependent steps against the fork's **own**
  secrets, and every such step is skipped cleanly when the secret is absent.

The result: a contributor can fork, push, and exercise the entire pipeline
(including a real deploy, if they add their own secrets) without a merge.

## Inputs

| Input | Default | Purpose |
| --- | --- | --- |
| `integration` | `false` | Run the generic Kind + Flux deploy. Requires the integration bits below. |
| `namespace` | repo name | Target namespace for the deploy. |
| `runner` | `ubuntu-latest` | Runner label for all jobs. |
| `op_version` | `v1.0.17` | Octopilot `op` builder image version. |
| `actions_ref` | `main` | Ref the composite steps resolve to (pin alongside the workflow for reproducibility). |

Secrets are passed with `secrets: inherit`. The pipeline uses (all optional):

- `SOPS_AGE_KEY` — decrypts the integration DB secret. **The user is responsible
  for adding this** to the repo/org.
- `ANTHROPIC_API_KEY` — used by AI-generated release notes on tags. **User-supplied.**
  Absent, the GitHub Release falls back to GitHub's generated notes.

## Release semantics (tags)

Pushing a `v*` tag runs the full DAG and then **Release (publish)**:

- **Promotion, not rebuild.** The exact digests that were built, pushed to
  ttl.sh, and (with `integration: true`) deployed and Helm-tested in Kind are
  copied with `crane cp` to `ghcr.io/<owner>/<basename>:<tag>`. Released
  digests == tested digests; the public ttl.sh hop cannot substitute content
  because the copy is digest-pinned.
- **Owner-relative naming.** Targets use `github.repository_owner`, so a fork's
  tag releases into the fork's own GHCR namespace — fork-safe like the rest of
  the pipeline.
- **`release-build-result` artifact** (90-day retention) carries the released
  refs in the `build_result.json` contract for downstream deploy tooling.
- **Constraint:** ttl.sh refs expire (~1h). Re-running just the release job
  much later will fail — re-run the whole workflow from the tag instead.
- **Permissions:** the job needs `contents: write` (GitHub Release) and
  `packages: write` (GHCR push) from the caller's token; org-default
  read/write permissions suffice.

## Environment promotion — the acceptance cycle

GHCR is the **dev gate** only. Further environments each target a per-project
GCP Artifact Registry via the reusable
`octopilot/actions/.github/workflows/acceptance-cycle.yml` — one call per
environment, chained sam-style (staging `needs:` nothing, production `needs:
staging`), each hop doing **promote → deploy → acceptance-test**:

- **Promote** copies the released digests from the previous hop's registry
  (GHCR for the first hop, the prior environment's AR after) into this
  environment's registry — digest-pinned `crane cp`, verified after copy, ref
  list from the release's `release_result.json` asset.
- **Deploy** (opt-in: set `gke_cluster`) reconciles the app's Flux
  HelmRelease(s) and watches rollout.
- **Acceptance tests** run `hack/acceptance-tests.sh` when present
  (receives `ENVIRONMENT`, `VERSION`).

Per-project config (registry, WIF provider, service account, cluster) lives in
the caller; GitHub environment protection rules provide the approval gates.
Auth is keyless (Workload Identity Federation). See the header of
`acceptance-cycle.yml` for a complete caller example.

## `integration: true` — the conventions

`integration: true` asserts that the repo has produced the integration bits (this
is deliberately opt-in — you build the chart and manifests once). The deploy job
then discovers everything and needs no per-repo workflow code:

1. **A Helm chart**, detected from `skaffold.yaml` (a `*-chart` build artifact).
   The chart should:
   - render images from values the overlay injects,
   - carry a **pre-install migration hook** (a Job running your migration binary)
     if it needs a schema, and
   - carry a **Helm test hook** (`helm.sh/hook: test`) that smoke-tests the app —
     this is what makes deploy *and* test "free": Flux runs it via
     `spec.test.enable: true` and a failing test fails the deploy.
2. **A Flux overlay at `k8s/env/ci`** (`OCIRepository` + `HelmRelease`) whose
   HelmRelease injects each image via `${IMG_<sanitized-image-name>}` (e.g.
   `ghcr.io/org/myapp-api` → `IMG_myapp_api`) and the chart via `${CHART_OCI_URL}`
   / `${CHART_REF_TYPE}` / `${CHART_REF_VALUE}`. The job runs
   `kubectl kustomize k8s/env/ci | envsubst | kubectl apply`, then **discovers**
   the `OCIRepository`/`HelmRelease` names via `kubectl get` and reconciles them.
3. **Optional ephemeral deps at `hack/ci-deps/`** (e.g. redis/postgres) — applied
   and waited on if present.
4. **Optional SOPS runtime profile** under `deployment-configuration/…/runtime/`
   (RERP layout): a `*.secrets.env` plus a `kustomization.yaml` whose
   `secretGenerator` names the Secret your chart consumes. The job finds the
   file, reads the Secret name from the kustomization, decrypts with
   `SOPS_AGE_KEY`, and creates the Secret — nothing hardcoded in the workflow.

Everything repo-specific therefore lives in **repo data** (chart, overlay,
ci-deps, SOPS profile), not in workflow code.

## Versioning & the bump

- Pin `@v1` for reproducibility; the Octopilot bot bumps a fleet with a one-line
  `@v1` → `@v2` PR across subscribed repos.
- `@main` auto-follows — handy while iterating; not recommended for production.
- `actions_ref` lets the reusable workflow pass its own version down to the
  composite actions so a `@v1` pin freezes the whole chain.

## Subscribe to CI

Because adoption is a 5-line caller, the Octopilot bot can onboard a repo by
committing that file (pinned to `@v1`) when a repo opts in via its
`Subscribe to CI` config — and bump the fleet by raising `@vN` PRs. The reusable
workflow is the single artifact that makes both trivial.
