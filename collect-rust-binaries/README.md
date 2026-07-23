# collect-rust-binaries

Copies top-level Cargo **debug** / **release** binaries (and shared libs) into
`build_artifacts/{debug,release}/` for `actions/cache` and downstream jobs.

Does **not** copy `deps/`, `incremental/`, `build/`, sidecars (`*.d`,
`*.rlib`, `*.rmeta`), or codegen companions matching `*_gen` — those are what
made full `target/` caches multi‑GB.

## Layout

```
build_artifacts/
  debug/<bin>
  release/<bin>
  manifest.txt          # path, size, sha256 per file
```

## Usage

From a sibling composite action:

```bash
bash "${{ github.action_path }}/../collect-rust-binaries/collect.sh" \
  "${GITHUB_WORKSPACE}/target" \
  "${GITHUB_WORKSPACE}/build_artifacts"
```

Or as a composite: `octopilot/actions/collect-rust-binaries@main`.

Set `COLLECT_APPEND=1` to merge another target tree without wiping.

**Append is the default across the pipeline.** Every collecting job (lint,
test legs, deliverables, validate) restores the same `cargo-deps` cache
family, and GitHub caches are first-writer-wins per key — so a partial build
(e.g. a BDD leg that only compiled the 8 crates its features touch) must
merge onto the restored `build_artifacts` tree, never replace it. Append mode
also dedupes manifest lines for re-collected files. Stale binaries from
deleted/renamed crates linger until the cache key rotates (Cargo.lock
change); acceptable for a cache.

## Per-binary artifacts

With `upload: per-binary` the action additionally uploads every collected
file of `upload-profile` (default `release`) as its **own** run artifact
named `<upload-prefix><binary>` (default `bin-<binary>`). Plain
`actions/upload-artifact` is one static step per artifact, so the action
drives the `@actions/artifact` toolkit from a script (`upload-each.mjs`) —
N artifacts from one step, delete-then-upload so re-run attempts don't
collide with their predecessors.

Downstream jobs then pull exactly what they need:

```yaml
- uses: actions/download-artifact@v4
  with:
    name: bin-hauliage_migrator
    path: bin/
```

The pipeline enables this in **integration-validate** (the canonical
whole-workspace release build), so per-binary artifacts exist once per run
without duplicate uploads from lint/test/deliverable legs.
