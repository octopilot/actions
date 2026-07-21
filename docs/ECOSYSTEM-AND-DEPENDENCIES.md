# Ecosystem & Dependencies

How a repo declares the **runtime services its application needs** (databases,
caches, brokers, mock IdPs) so the Octopilot integration deploy can stand the
app up in an ephemeral Kind cluster — and how to choose between the mechanisms.

## Philosophy

Octopilot provisions **build** infrastructure and orchestrates **deploys**. It
never provisions application ecosystem dependencies itself — that knowledge
belongs to the repo. Instead, the pipeline offers ordered, convention-based
extension points that the repo fills in. If a dependency isn't declared
through one of these conventions, the deploy stage will fail honestly when the
app can't reach it.

## The extension points (in execution order)

The `integration-deploy` job runs these steps against a fresh Kind cluster:

1. **Namespace** — `NS` = repo name (or the `namespace` input).
2. **Profile** — `deployment-configuration/profiles/<profile>/` (selected by
   the `profile` input, default `dev`): the first `kustomization.yaml` found
   is applied; `*.secrets.env` files are SOPS-decrypted first (requires
   `SOPS_AGE_KEY`; skipped on fork PRs). This is where app config/secrets
   (connection strings, hostnames) come from.
3. **`hack/ci-deps/`** — every manifest in this directory is
   `kubectl apply`-ed (no `-n` flag — see below), then the pipeline waits
   (180s) for Deployments in the app namespace, plus any `tier: ci-deps`
   labelled Deployments in other namespaces. **This is the designated home
   for ephemeral, CI-only service dependencies.**

   Contract: ci-deps manifests are **self-describing** — every object MUST
   declare `metadata.namespace` explicitly (the pipeline passes no `-n`,
   because kubectl refuses objects whose declared namespace differs from it,
   which would break legitimate cross-namespace shims). Label everything
   `tier: ci-deps` so cross-namespace readiness waits find it.
4. **Flux overlay** — `k8s/env/ci` is kustomized, `envsubst`-ed with
   `IMG_<name>` / `CHART_*` variables, applied, and reconciled
   (OCIRepositories 2m, HelmReleases 8m).

## Test-phase dependencies: `hack/test-deps/` (the BDD convention)

The **Test job** (not the integration deploy) runs on a plain runner with
Docker. Repos whose test suites need live services — BDD suites against
Postgres, integration tests against Redis or a broker — declare them once in
`hack/test-deps/docker-compose.yml` (or `compose.yaml`). Before running the
test command, the test action executes:

    docker compose -f hack/test-deps/docker-compose.yml up -d --wait

`--wait` blocks on compose **healthchecks**, so declare one per service (the
compose-native equivalent of the ci-deps readiness contract). No teardown is
needed — runners are ephemeral.

Connection details are the test command's business: export `TEST_DB_*` (or
whatever your harness reads) inside `BP_TEST_COMMAND`. When the ritual is more
than a line, put it in a **committed script** (`hack/test.sh`) and declare
`BP_TEST_COMMAND=./hack/test.sh` — versioned, reviewable, and runnable locally
with the same compose file (`docker compose -f hack/test-deps/docker-compose.yml
up -d --wait && ./hack/test.sh`).

This replaces per-repo GitHub Actions `services:` blocks: the reusable
pipeline cannot know your services, but your repo can declare them.

## Decision guide: where does my dependency go?

| Mechanism | Use when | Avoid when |
|-----------|----------|------------|
| **`hack/ci-deps/` manifests** (DEFAULT for deploy phase) | The dep is CI-only scaffolding: a throwaway Postgres/Redis/mock. Plain Deployment+Service, `emptyDir` storage, fixed dev credentials matching the profile's secrets. | The dep's lifecycle must mirror production (operators, HA, migrations-as-jobs). |
| **`hack/test-deps/` compose file** (DEFAULT for test phase) | Unit/BDD suites in the Test job need `localhost` services (Postgres for a BDD harness). Healthchecked compose services; test command exports its own connection env. | The dep must run inside the Kind cluster (that is the deploy phase — use ci-deps). |
| **Flux overlay HelmRelease** (`k8s/env/ci`) | Production ALSO runs the dep via Flux (operator or chart) and you want topology parity in CI. Use `dependsOn` to order app after dep. | You just need "a Postgres" — a full chart/operator pull slows every CI run for no extra confidence. |
| **Subchart toggle** (`postgresql.enabled` in the app chart) | The PRODUCT genuinely ships an embedded-dependency mode to end users. The toggle is a product feature, not a CI convenience. | You'd only ever enable it in CI. That leaks CI concerns into the product chart and bloats it with infra it doesn't own. |
| **GitHub Actions `services:`** | Only in repo-owned workflows outside the reusable pipeline (e.g. a legacy bdd.yml being migrated). | Anything the reusable pipeline runs — it cannot know your services; declare them in hack/test-deps instead. |

Rule of thumb: **test-deps for the Test job, ci-deps for the Kind deploy,
overlay for parity, subchart only for product features.**

## Gotcha: hostname conventions must agree

The most common deploy failure is not a missing dependency but a **hostname
mismatch** between config layers. Real example (fleetingdns): the SOPS
`DATABASE_URL` used the namespace-local host `postgres`, while
`application.properties` used the production-shaped
`postgres.data.svc.cluster.local` — a shared `data` namespace that exists in
production but not in Kind. Half the app connected; half didn't.

Two remedies:

1. **Align the profile** — point all host references at the ci-deps service
   (namespace-local). Right when the profile is CI-owned.
2. **DNS shim in ci-deps** — create the production-shaped namespace and an
   `ExternalName` Service aliasing it to the ci-deps instance:

   ```yaml
   apiVersion: v1
   kind: Namespace
   metadata: { name: data, labels: { tier: ci-deps } }
   ---
   apiVersion: v1
   kind: Service
   metadata: { name: postgres, namespace: data, labels: { tier: ci-deps } }
   spec:
     type: ExternalName
     externalName: postgres.<repo-namespace>.svc.cluster.local
     ports: [{ port: 5432 }]
   ```

   Right when the profile is shared with real environments and must keep
   production-shaped hostnames. The shim lives in ci-deps — visibly CI-only.

## Checklist for agents (and humans) when integration-deploy fails

Work through these in order — each maps to a config layer above:

1. **Read the HelmRelease/pod diagnostics** the pipeline dumps on reconcile
   failure (events, pod describes, job logs are printed in the job output).
2. **Connection refused / DNS errors?** Compare every host in
   `deployment-configuration/profiles/<profile>/application.properties` and
   the decrypted `*.secrets.env` against the Services actually created by
   `hack/ci-deps/` (names AND namespaces). Mismatch → align profile or add an
   ExternalName shim (above).
3. **Dependency pod not ready?** ci-deps Deployments must pass readiness
   within 180s: check probes, image pull, and that data dirs use `emptyDir`
   (Postgres needs `PGDATA` under a subdirectory to avoid the
   `lost+found` init failure).
4. **Missing secret/config?** The profile kustomization defines the names the
   chart consumes; `SOPS_AGE_KEY` absent (fork PR) means secrets were
   skipped — expected, not a bug.
5. **Image not found?** The overlay consumes `IMG_<sanitized-image-name>`
   env vars from `build_result.json` — the image basename `myapp-api`
   becomes `${IMG_myapp_api}`.
6. **Adding a new dependency?** Default to a single manifest file in
   `hack/ci-deps/` with fixed dev credentials that match the profile, a
   readiness probe, and `tier: ci-deps` labels. Only reach for the overlay or
   a subchart per the decision guide.

## What octopilot deliberately does NOT do

- Guess your dependencies from code. Declarations only.
- Ship "blessed" dependency manifests. Your Postgres flags are yours.
- Manage dependency lifecycles beyond apply-and-wait. Operators and
  migrations belong to the repo's overlay or chart.

This boundary is what keeps the pipeline generic: a react+go sample and an
18-service Rust monorepo use the same four extension points.
