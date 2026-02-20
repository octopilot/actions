# verify-registry

Waits for an `octopilot/registry-tls` GitHub Actions service container to become
ready, configures the Docker daemon to trust its self-signed TLS certificate, and
optionally validates push/pull access.

## Why this exists

`ghcr.io/octopilot/registry-tls:latest` serves real HTTPS on internal port 5000
(exposed as host port 5001 by convention). Two things must happen before any job
step can push or pull images:

1. The Docker daemon must be configured to allow the self-signed certificate
   (`insecure-registries` in `/etc/docker/daemon.json`). Without this,
   `docker push` fails with a TLS error even though the registry is running.
2. The registry container needs a few seconds to initialise before it will serve
   `/v2/`. Probing too early causes spurious failures.

A common mistake is probing `http://localhost:5000/v2/` — wrong port **and** wrong
protocol. This action probes `https://localhost:5001/v2/` correctly.

## Usage

Declare the registry service in your job, then call this action before any step
that pushes or pulls images:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    services:
      registry:
        image: ghcr.io/octopilot/registry-tls:latest
        ports:
          - 5001:5000

    steps:
      - uses: actions/checkout@v4

      - name: Verify registry
        uses: octopilot/actions/verify-registry@main
        # all inputs are optional — defaults work for the standard setup

      - name: Build and push
        run: |
          docker build -t localhost:5001/my-image:latest .
          docker push localhost:5001/my-image:latest
```

## Inputs

| Input | Description | Default |
|---|---|---|
| `port` | Host port the registry is exposed on | `5001` |
| `max_attempts` | Number of health-check retries before failing | `15` |
| `retry_delay` | Seconds between health-check attempts | `2` |
| `test_push` | Push a test image to verify write access | `true` |

## Outputs

| Output | Description |
|---|---|
| `registry_url` | Full registry URL, e.g. `localhost:5001` |

## What it does

1. **Configures Docker daemon** — writes `{"insecure-registries": ["localhost:5001"]}`
   to `/etc/docker/daemon.json` and restarts Docker. Required for self-signed TLS.
2. **Health-check loop** — polls `https://localhost:5001/v2/` with `curl -k` until
   it returns a 2xx or retries are exhausted. On failure, dumps `docker ps` and
   verbose curl output for debugging.
3. **Test push/pull** — tags `hello-world:latest` as a probe image and pushes it to
   confirm write access. Cleans up afterwards.
