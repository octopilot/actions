# Zero-Config Octopilot: Convention-First Detection

Status: DESIGN (2026-07-21). Prior art: everything in this repo; the hauliage /
fleetingdns / BRRTRouter adoptions are the evaluation dataset.

## The idea

Today a repo adopts octopilot by committing two files: `skaffold.yaml` (the
shape) and a ~12-line workflow caller. The proposal: make **both optional**.
Detection synthesizes the shape from what the ecosystem's own files already
declare, and org-level machinery supplies the workflow. Onboarding a project
becomes a merge of a one-commit bot PR — or nothing at all.

## What skaffold.yaml actually encodes (audit of our three adoptions)

| Encoded fact | Mechanically inferable? | From where |
|---|---|---|
| Language contexts | YES (done) | marker files |
| Workspace members, bins, libs | YES | `cargo metadata` |
| Nested workspace root | YES | walk for Cargo.toml with `[workspace]` |
| Charts | YES (done) | Chart.yaml glob |
| Test rituals | YES (done) | archetype synthesis + hack/test-*.sh |
| Test/CI service deps | YES (done) | hack/test-deps, hack/ci-deps |
| Builder image | YES | org convention + language |
| **Deployable vs dev tool** | NO | judgment (hauliage: 22 of ~30 bin crates) |
| **Image grouping** | NO | deploy topology (fleetingdns api = api-bin+migration because the chart hook says so) |
| **Runtime assets (KEEP)** | PARTIAL | `CARGO_MANIFEST_DIR`/`include_str!` heuristics catch some; intent catches the rest |
| **Publish intent (lib/bin)** | NO | business decision |
| Image naming | CONVENTION | `<registry>/<repo>-<kebab(bin)>` covers all our real cases |

Conclusion: ~80% of every skaffold.yaml we wrote is transcription of facts the
repo already states elsewhere. The other ~20% is intent — and intent has a
better home than a new file.

## The three layers (progressive disclosure)

Detection resolves top-down; **every layer emits the identical
pipeline-context**, so the pipeline, actions, and buildpacks are untouched.


Layer 2  skaffold.yaml            (escape hatch — wins when present; today's repos unchanged)
Layer 1  inline metadata          ([package.metadata.octopilot] / package.json "octopilot" / Chart.yaml annotations)
Layer 0  pure convention          (cargo metadata + archetypes + org defaults)


### Layer 0 conventions (rust)

- Every workspace member with a `[[bin]]`/`src/main.rs` target is a deployable
  image, EXCEPT members matching dev-tool conventions: names/paths matching
  `*mock*`, `*load_test*`, `*bench*`, `examples/`, or `publish = false` +
  no chart/k8s reference.
- Image name: `<registry>/<repo>-<kebab(package)>` (registry from org config).
- Library crates (no bin target) fold into ONE `-lib` deliverable
  (`BP_LIB_PACKAGES` = all libs, `publish = none`).
- Nested workspace: first ancestor `Cargo.toml` with `[workspace]` sets
  `BP_RUST_WORKSPACE_DIR`.
- Runtime-asset heuristic: crates whose sources reference
  `CARGO_MANIFEST_DIR`, `include_str!`/`include_bytes!` of non-`src/` paths
  get those paths auto-KEEPed; anything else needs Layer 1.

### Layer 0 conventions (frontend — the missing archetypes)

| Signal | Archetype | Build function |
|---|---|---|
| `package.json` + vite/CRA/astro config, no server entry | static site | web-server buildpack image serving `dist/` — or a `-static` deliverable (bucket/CDN upload) since artifacts are not always images |
| `next.config.*` / nuxt / sveltekit with server output | SSR service | node buildpack image, `web` process |
| `dist/` consumed by a sibling rust bin (BFF pattern) | embedded | no image; the consuming bin's KEEP includes the built `dist/` |
| `package.json` with `bin` field, no app framework | CLI | `-bin` deliverable |

### Layer 1: intent lives in files the ecosystem already owns

```toml
# Cargo.toml of a workspace member
[package.metadata.octopilot]
deployable = false                  # dev tool, never an image
group-with = "api-bin"              # ship this binary inside api's image (helm hook pattern)
keep = ["doc", "config", "static_site"]
function = "bin"                    # CLI: -bin deliverable instead of image
publish = "none"                    # lib verify-only
test-label = "bdd"                  # parallel test leg membership
```

`cargo metadata` surfaces `package.metadata` verbatim — detect reads it with
zero new parsers. package.json gets `"octopilot": {…}`; Chart.yaml gets
`annotations: {octopilot.io/...}`.

### Layer 2: skaffold.yaml

Wins outright when present. Also the **pinning mechanism**: repos that want
reproducibility over convenience freeze the synthesized plan.

## Trust and reproducibility guardrails

1. **The plan is always visible.** Detect uploads the synthesized
   `skaffold.yaml` as a run artifact and prints a one-screen plan summary in
   the Detect job. No silent guessing — the "no ears peaking" principle.
2. **`op detect --write`** materializes the synthesized plan into the repo.
   This is simultaneously the migration path (adopt by inspection), the
   debugging tool (diff what changed), and the escape to Layer 2.
3. **Convention pack is versioned.** The plan records `conventions: v1` and a
   plan hash; upgrading the pack cannot silently change builds — the Detect
   summary flags plan drift vs the previous run.

## Zero-file workflow delivery

An env var alone cannot trigger Actions — a workflow file must exist at the
ref. Two real mechanisms:

1. **Org-level required workflow** (GitHub ruleset): the octopilot pipeline
   runs for every repo in the org with literally zero files per repo.
   Constraints: ruleset scoping, PR-focused semantics, runner permissions.
2. **Octopilot bot** (GitHub App): detects a repo (or reads a repo topic /
   custom property like `octopilot=on`), opens a one-commit PR adding the
   12-line caller. "Book a project has CI" = merge the PR. The bot can also
   refresh callers org-wide when the pipeline evolves (solves today's
   version-skew-by-hand problem).

Recommendation: bot first (explicit, auditable, per-repo opt-in), ruleset
later for orgs that want CI as an invariant.

## Worked example: fleetingdns under Layer 0

Synthesized today from `cargo metadata` + conventions alone:

- api-bin, dnsd-bin, edgehub-bin → images `fleetingdns-{api,dnsd,edgehub}` ✓ (naming convention needs the `-bin` strip rule)
- migration → image `fleetingdns-migration` ✗ (should be grouped into api — needs Layer 1 `group-with`)
- edf-cli, fleetingdns-ctl, slot-setter → images ✗ (should be one `-bin` deliverable — needs Layer 1 `function = "bin"` or a `cmd/` convention)
- chart/fleetingdns → chart ✓
- crates/* libs → `-lib` deliverable ✓ (today's skaffold doesn't even declare this — Layer 0 exceeds it)

Three Layer-1 lines in three Cargo.tomls close the entire gap. That ratio —
~40 lines of skaffold.yaml replaced by 3 lines of inline metadata — is the
measure of whether this design carries its weight.

## What this is NOT

- Not a rewrite: detect.py grows a synthesis pass in front of the existing
  skaffold parser; everything downstream is untouched.
- Not removing skaffold.yaml support: Layer 2 is permanent.
- Not guessing at deploy topology: grouping/publish/keep stay explicit, just
  relocated into the manifests that already describe the package.

## Sequencing

1. `detect.py`: synthesis pass for rust via `cargo metadata` (Layer 0) +
   `[package.metadata.octopilot]` (Layer 1); plan artifact + summary output.
2. Frontend archetypes (hauliage frontend/ + portal/ as the test bed).
3. `op detect --write`.
4. Bot (separate repo; GitHub App; one-commit PR).
5. Org ruleset variant.


