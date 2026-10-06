# Rust images

A Rust service built by the Octopilot pipeline does not get a Dockerfile, and
it does not get a `command:` in the chart. The buildpack puts the binary in a
fixed place and the image's default process starts it. Most repos never name
that binary in `skaffold.yaml`.

This page is the contract. The buildpack version baked into the builder
matters; the [builder pin](#builder) is part of it.

## What you write

One crate, one image. `Cargo.toml` at the context root (or under
`BP_RUST_WORKSPACE_DIR`). The package name is the binary name.

```yaml
# skaffold.yaml
- image: ghcr.io/octopilot/igniteflux
  context: .
  buildpacks:
    builder: ghcr.io/octopilot/builder-jammy-base:rust-builder-c3c756a
    runImage: ghcr.io/octopilot/igniteflux-base:latest
    env:
      - BP_TEST_COMMAND=./hack/test-unit.sh
      - BP_TEST_LABEL=unit
```

```yaml
# chart container — no command, no args
containers:
  - name: igniteflux
    image: {{ .Values.image.ref | quote }}
```

Leave `BP_RUST_BINARY_NAME` unset. For this crate Cargo already calls the
binary `igniteflux`. The chart starts the image default process, which runs
that binary.

Do not set `BP_DEFAULT_PROCESS`. That variable belongs to a Paketo buildpack
this pipeline does not run. The Rust buildpack never reads it.

## Where the binary is, and what starts it

| Piece | Value |
| --- | --- |
| File in the image | `/workspace/bin/<cargo-bin-name>` |
| Default process | `web`, command `bin/<cargo-bin-name>`, working directory `/workspace` |
| Named process | `/cnb/process/<cargo-bin-name>` — same binary |
| What Kubernetes runs | The image default process, when the chart sets no `command` |

The path is relative on purpose. The CNB launcher `chdir`s to `/workspace`
and then execs `bin/<name>`. A chart that sets `command: ["/workspace/bin/igniteflux"]`
bypasses that and depends on the entrypoint still being the launcher. Omit
`command` on the main container.

A second binary in the same image (a migration, a worker) is started by name:

```yaml
command: ["/cnb/process/migration"]
```

`/cnb/process/migration` is a symlink to the launcher, not a copy of the
binary. The launcher looks up the process type `migration` and runs
`bin/migration` from `/workspace`. The hook and the service can share one
image. `BP_RUST_PACKAGES` is how that image is limited to those crates
instead of the whole workspace.

## How the name is chosen

Cargo already has a name for the binary. The pipeline should not ask you to
repeat it.

| Situation | Default process | What you set |
| --- | --- | --- |
| One bin in the image | That bin | Nothing |
| Several bins, and `Cargo.toml` has `default-run` | The `default-run` target | Nothing in skaffold. `default-run` is the same field `cargo run` uses |
| Several bins, no `default-run`, one bin named after the package | That bin | Nothing |
| Several bins and none of the above | Build fails and lists the bins it found | `BP_RUST_BINARY_NAME` **or** `default-run` |

`BP_RUST_BINARY_NAME` is only that last override. It is not how a normal
service is named.

`BP_RUST_PACKAGE` and `BP_RUST_PACKAGES` choose which crates are compiled
into the image. They do not rename the binary. After the filter below, a
single `-p` package with one bin needs neither variable.

Every real bin still gets `/cnb/process/<name>`, including the one that is
also `web`. A Helm hook addresses the hook by that name. It does not care
which process is the default.

## What the published buildpack does today

The builder pin `rust-builder-c3c756a` contains `octopilot/rust` **0.1.14**
(lifecycle 0.21.22). That release does not implement the selection table
above yet. It is the same launch behavior as 0.1.13, plus cache sweeping.

On those versions:

- Any Cargo artifact with an executable path is copied into `/workspace/bin`,
  including build scripts. The first one Cargo prints becomes `web`.
- `BP_RUST_BINARY_NAME` is read only when that scan finds nothing. A
  successful `cargo build` ignores it. Setting it in `skaffold.yaml` does
  not select the process.
- A crate with no `build.rs` and one bin still lands on the right file,
  because that bin is the only executable. igniteflux is in this set, which
  is why the variable can be deleted there today.
- A crate with `build.rs`, or a workspace image with several bins, can boot
  the wrong process. Do not paper over that with `BP_RUST_BINARY_NAME` until
  the buildpack honors it on a successful build.

`octopilot/rust` 0.1.15 applies that table: only `kind = bin` becomes a
process, `default-run` and the package name choose `web`, and
`BP_RUST_BINARY_NAME` is an override that is honored on a successful build.
A failed prune that drops `bin/<name>` fails the build. 0.1.15 is not in
builder `rust-builder-c3c756a`. Until a builder is published with it, prefer
one bin per image and no `build.rs` in the crate you are packaging.

## Builder

Pack artifacts use the Octopilot builder, not
`paketobuildpacks/builder-jammy-base`. The upstream builder has no
`octopilot/rust` buildpack, so a Rust context built with it does not produce
this layout.

```yaml
builder: ghcr.io/octopilot/builder-jammy-base:rust-builder-c3c756a
```

That tag is the image behind `:latest` (`octopilot/rust` 0.1.14, lifecycle
0.21.22, config `sha256:b8db544fac01`). Pin the immutable tag. `:latest` moves when the builder is
published. `rust-builder-d5eb42a` is rust 0.1.6: the binary is at
`/workspace/bin/<name>` and the image has no launch processes, so the
container exits with no default process.

`detect-contexts` fills this pin in when `skaffold.yaml` omits `builder:`.
An explicit `builder:` is passed through, so a stale tag in the file wins.

## Run image

A custom `runImage` (Ubuntu plus git, kustomize, and so on) is fine. Two
constraints:

- `CMD` must be empty. Ubuntu's `CMD ["/bin/bash"]` becomes the launcher's
  command, and the image then has no default process to start.
- `/workspace` must be traversable by the run user (`0755`). Buildpack
  0.1.12 left it mode `700`; 0.1.13 fixes that. The retired builder tag
  above does not include the fix.

The launcher is injected at export. It does not have to be in your
Dockerfile. The binary does not have to be on `PATH`.

## Build-time variables that do belong in skaffold

| Variable | When |
| --- | --- |
| `BP_RUST_WORKSPACE_DIR` | `Cargo.toml` is not at the context root |
| `BP_RUST_PACKAGE` | Build one workspace member |
| `BP_RUST_PACKAGES` | Build a chosen set into one image (service + migration) |
| `BP_RUST_KEEP` | Runtime files the binary opens from the source tree (OpenAPI specs, static files). Everything else under the app dir is deleted |
| `BP_TEST_COMMAND` / `BP_TEST_LABEL` | The pipeline test leg, not the image |

`BP_RUST_KEEP` is a path list relative to the app dir, comma-separated. It
does not change the binary name or the process.
