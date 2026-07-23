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
