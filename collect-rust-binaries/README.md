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
