# scale-min-replicas

DST- and timezone-aware day/night scaling of a Helm values key (typically
`minReplicas`). The action decides the target value from the **local wall clock**
in an IANA timezone — DST is applied by the OS tz database, so there is nothing
to configure twice a year — writes it into a values file, and commits + pushes.

## The DST problem, solved

GitHub `schedule` cron expressions run in fixed UTC. A schedule like
`0 5 * * *` → "scale up" drifts against the local day as DST shifts the offset,
so winter and summer land on different local times. This action removes the
drift by construction:

1. The decision is always computed from `now` in your `timezone` (current
   offset applied automatically).
2. Your cron times are chosen inside a **safe band**: UTC hours where the
   resulting local time is *day* for every sunrise fire and *night* for every
   sunset fire, across **every offset the zone has used** (sampled over 2
   years — enough to cover any DST rule the IANA database has ever flipped).
   Winter runs may fire exactly at the boundary; summer runs fire one hour
   later — same decision, both seasons.
3. Every run logs `local_time`, `utc_offset`, and `decision` in the job
   summary, and the safe band is re-printed on every run so a misconfigured
   schedule is visible immediately.

### Picking your cron times

Set `cron_band: true` (default) and read the printed band, or compute it
once locally:

```bash
python3 resolve_scale.py --values-file any.yaml --key minReplicas \
  --timezone Europe/Berlin --sunrise 8 --sunset 20 --day 3 --night 1 \
  --print-cron-band
```

Example — Berlin, day window 08:00–20:00 local (offsets +1 winter / +2 summer):

```
Sunrise cron - safe UTC hours: [7, 8, ..., 17]  (recommended: 07)
Sunset cron  - safe UTC hours: [19, 20, ..., 5] (recommended: 19)
  07:00 UTC -> 08:00 local (offset +1)   # winter: exactly sunrise
  07:00 UTC -> 09:00 local (offset +2)   # summer: 1h after sunrise
  19:00 UTC -> 20:00 local (offset +1)   # winter: exactly sunset
  19:00 UTC -> 21:00 local (offset +2)   # summer: 1h after sunset
```

So: `0 7 * * *` (sunrise) and `0 19 * * *` (sunset).

Rule of thumb: **sunrise cron ≈ sunrise − winter offset, sunset cron ≈
sunset − summer offset**; if that lands on a DST-ambiguous hour (the one the
offset shift itself crosses), the band output's recommendation picks the
nearest safe one. Wrap-around day windows (e.g. 22:00–06:00) and
southern-hemisphere zones (negative offsets) work identically; the band math
is offset-symmetric.

## Inputs

| Input | Description | Default |
|---|---|---|
| `values_file` | Path to the Helm values file (relative to workspace root). | — (required) |
| `key` | YAML key to update. Matched at any indentation; inline comments preserved. | `minReplicas` |
| `timezone` | IANA timezone of the business location. | — (required) |
| `sunrise_hour` | Local hour (0–23) the day window opens. | — (required) |
| `sunset_hour` | Local hour (0–23) the day window closes. `<= sunrise_hour` gives a wrap-around window. | — (required) |
| `daytime_min_replicas` | Value during the day window. | — (required) |
| `nighttime_min_replicas` | Value outside the day window. | — (required) |
| `sunday_rest` | When `true`, Sundays always resolve to the nighttime value (no morning scale-up; Monday's sunrise cron restores the day value). | `false` |
| `min_replicas` | Explicit override for manual dispatches. Empty = auto day/night decision. | `''` |
| `commit_prefix` | Commit message prefix. | `chore(prod)` |
| `branch` | Branch to check out and push to. | `master` |
| `token` | GitHub token with `contents: write`. | `${{ github.token }}` |
| `event` | Commit message tag: `schedule` → `(cron)`, `workflow_dispatch` → `(dispatch)`. | `schedule` |
| `cron_band` | Print the safe UTC cron hours for this window on every run. | `true` |

## Outputs

| Output | Description |
|---|---|
| `decision` | `daytime`, `nighttime`, `sunday-rest`, or `explicit`. |
| `resolved_min_replicas` | Value applied (or that would be applied). |
| `local_time` / `utc_offset` / `weekday` | The resolved local instant, for auditing. |
| `changed` | `true` if the values file was modified. |
| `commit_sha` | SHA of the created commit; empty on no-op. |
| `cron_band` | (informational, also in the job summary) safe UTC cron hours. |

## Sunday rest

With `sunday_rest: true` the decision order is: explicit override → Sunday →
day window → night. So Sunday's sunrise cron fires and resolves to the
nighttime value (no-op if already there — no commit), and Monday's sunrise
cron restores the daytime value. Sunday's sunset cron is likewise a no-op.
No extra cron entry is needed.

## Example workflow

```yaml
name: Scale minReplicas (prod, Europe/Berlin)
on:
  schedule:
    - cron: '0 7 * * *'    # sunrise: 08:00 CET / 09:00 CEST local
    - cron: '0 19 * * *'   # sunset: 20:00 CET / 21:00 CEST local
  workflow_dispatch:
    inputs:
      min_replicas:
        description: 'Explicit minReplicas override (empty = auto)'
        required: false
        default: ''
        type: string

permissions:
  contents: write

jobs:
  scale:
    runs-on: ubuntu-latest
    steps:
      - uses: octopilot/actions/scale-min-replicas@main
        with:
          values_file: deployment-configuration/profiles/prod-cf/helm/values.yaml
          timezone: Europe/Berlin
          sunrise_hour: 8
          sunset_hour: 20
          daytime_min_replicas: 3
          nighttime_min_replicas: 1
          sunday_rest: true
          min_replicas: ${{ inputs.min_replicas }}
          event: ${{ github.event_name }}
```

`${{ inputs.min_replicas }}` is empty on schedule runs (auto mode) and holds
the dispatched choice on manual runs — no conditional needed. An empty
dispatch value also auto-decides from the clock. The action no-ops (no commit)
when the file already holds the target value.

## Testing the decision logic without a runner

`resolve_scale.py` accepts `--now-utc` (ISO 8601) and `--dry-run`, which is
what the test suite in `tests/unit/test_scale_min_replicas.py` uses:

```bash
python3 resolve_scale.py --values-file values.yaml --key minReplicas \
  --timezone Europe/Berlin --sunrise 8 --sunset 20 --day 3 --night 1 \
  --sunday-rest true --now-utc 2026-09-03T07:00:00Z --dry-run
# Decision: daytime (local 2026-09-03T09:00:00+02:00, +02:00, Thursday)
```
