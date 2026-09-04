#!/usr/bin/env python3
"""Day/night scaling decision + values.yaml update for scale-min-replicas.

Standard library only. The composite action invokes this once; it resolves the
day/night decision from the local wall clock (IANA timezone, DST applied by the
OS tz database), updates the values file, and writes results to GITHUB_OUTPUT.

Also exposes a `--print-cron-band` mode that computes, for a timezone and a
day window, which UTC cron hours are safe for sunrise/sunset scheduling
across every offset the zone has used in the sampled years.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from datetime import UTC
except ImportError:  # Python < 3.11 (ubuntu-latest runners ship 3.10)
    UTC = timezone.utc

SUNDAY = 6
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DECISION_MESSAGES = {
    "daytime": ("Sunrise", "set"),
    "nighttime": ("Sunset", "set"),
    "sunday-rest": ("Sunday rest", "hold"),
    "explicit": ("Manual scale", "set"),
}

EVENT_SUFFIXES = {
    "schedule": "cron",
    "workflow_dispatch": "dispatch",
}


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)  # noqa: T201
    sys.exit(1)


def parse_hour(value: str, name: str) -> int:
    try:
        hour: int = int(value)
    except ValueError:
        fail(f"{name} must be an integer 0-23, got {value!r}")
    if not 0 <= hour <= 23:
        fail(f"{name} must be an integer 0-23, got {hour}")
    return hour


def parse_replicas(value: str, name: str) -> int:
    try:
        replicas: int = int(value)
    except ValueError:
        fail(f"{name} must be a non-negative integer, got {value!r}")
    if replicas < 0:
        fail(f"{name} must be a non-negative integer, got {replicas}")
    return replicas


def parse_bool(value: str, name: str) -> bool:
    if value.lower() not in ("true", "false"):
        fail(f"{name} must be 'true' or 'false', got {value!r}")
    return value.lower() == "true"


def load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        fail(f"unknown IANA timezone {name!r}")


def in_day_window(local_hour: int, sunrise: int, sunset: int) -> bool:
    """Day window membership; supports sunset < sunrise (wrap-around windows)."""
    if sunrise == sunset:
        return False
    if sunrise < sunset:
        return sunrise <= local_hour < sunset
    return local_hour >= sunrise or local_hour < sunset


def decide(
    now_local: datetime,
    sunrise: int,
    sunset: int,
    sunday_rest: bool,
    override: int | None,
    day: int,
    night: int,
) -> tuple[int, str]:
    """Return (value, decision)."""
    if override is not None:
        if override == day:
            decision = "daytime"
        elif override == night:
            decision = "nighttime"
        else:
            decision = "explicit"
        return override, decision
    if sunday_rest and now_local.weekday() == SUNDAY:
        return night, "sunday-rest"
    if in_day_window(now_local.hour, sunrise, sunset):
        return day, "daytime"
    return night, "nighttime"


def format_offset(dt: datetime) -> str:
    offset = dt.utcoffset()
    if offset is None:  # unreachable: now_local is always tz-aware
        fail("missing UTC offset")
    total_minutes = int(offset.total_seconds()) // 60
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def build_commit_message(prefix: str, key: str, value: int, decision: str, event: str) -> str:
    label, verb = DECISION_MESSAGES[decision]
    suffix = EVENT_SUFFIXES.get(event, "")
    tail = f" ({suffix})" if suffix else ""
    return f"{prefix}: {label} - {verb} {key} to {value}{tail}"


def update_values_file(path: str, key: str, value: int, dry_run: bool) -> tuple[bool, int]:
    """Replace '<key>: <n>' at any indentation. Returns (changed, current_value)."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    lines = text.splitlines()
    pattern = re.compile(rf"^(\s*){re.escape(key)}(\s*:\s*)(-?\d+)\s*(#.*)?$")
    matches = [i for i, line in enumerate(lines) if pattern.match(line)]
    if not matches:
        fail(f"key {key!r} not found in {path}")
    if len(matches) > 1:
        fail(f"key {key!r} appears {len(matches)} times in {path}; ambiguous")

    index = matches[0]
    match = pattern.match(lines[index])
    if match is None:  # unreachable: the line came from the same pattern scan
        fail(f"key {key!r} not found in {path}")
    current = int(match.group(3))
    if current == value:
        return False, current

    comment = match.group(4) or ""
    suffix = f"  {comment}" if comment else ""
    lines[index] = f"{match.group(1)}{key}{match.group(2)}{value}{suffix}"

    if not dry_run:
        trailing_newline = "\n" if text.endswith("\n") else ""
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + trailing_newline)
    return True, current


def zone_offsets(tz: ZoneInfo, start_year: int, years: int) -> list[int]:
    """Distinct UTC offsets (hours) the zone has used across the sampled window."""
    offsets: set[int] = set()
    moment = datetime(start_year, 1, 1, tzinfo=UTC)
    end = datetime(start_year + years, 12, 31, 23, 0, tzinfo=UTC)
    while moment <= end:
        offset = moment.astimezone(tz).utcoffset()
        if offset is None:  # unreachable: UTC-anchored aware datetime
            fail("missing UTC offset")
        offsets.add(int(offset.total_seconds()) // 3600)
        moment += timedelta(hours=6)
    return sorted(offsets)


def cron_candidates(offsets: list[int], sunrise: int, sunset: int, want_day: bool) -> list[int]:
    """UTC cron hours whose local time is (day: in-window / night: out-of-window)
    for EVERY offset the zone has used. Correct across wrap-around and the
    southern hemisphere."""
    candidates = []
    for hour in range(24):
        if all(in_day_window((hour + offset) % 24, sunrise, sunset) is want_day for offset in offsets):
            candidates.append(hour)
    return candidates


def recommended(candidates: list[int], preferred: int) -> int:
    """Prefer the candidate equal to `preferred`; else the nearest one."""
    if not candidates:
        fail("no safe UTC cron hour exists for this window")
    if preferred in candidates:
        return preferred
    return min(candidates, key=lambda h: min((h - preferred) % 24, (preferred - h) % 24))


def format_offsets(offsets: list[int]) -> str:
    return ", ".join(f"+{o}" if o >= 0 else str(o) for o in offsets)


def print_cron_band(tz: ZoneInfo, tz_name: str, sunrise: int, sunset: int, start_year: int, years: int) -> None:
    offsets = zone_offsets(tz, start_year, years)
    day_hours = cron_candidates(offsets, sunrise, sunset, want_day=True)
    night_hours = cron_candidates(offsets, sunrise, sunset, want_day=False)
    rec_day = recommended(day_hours, (sunrise - offsets[0]) % 24)
    rec_night = recommended(night_hours, (sunset - offsets[-1]) % 24)

    def cyclic(hours: list[int], start: int) -> list[int]:
        index = hours.index(start)
        return hours[index:] + hours[:index]

    print(f"Timezone: {tz_name}")  # noqa: T201
    print(f"Offsets sampled {start_year}-{start_year + years}: {format_offsets(offsets)}")  # noqa: T201
    print(f"Day window (local): {sunrise:02d}:00 - {sunset:02d}:00")  # noqa: T201
    print(f"Sunrise cron - safe UTC hours: {cyclic(day_hours, rec_day)} (recommended: {rec_day:02d})")  # noqa: T201
    print(f"Sunset cron  - safe UTC hours: {cyclic(night_hours, rec_night)} (recommended: {rec_night:02d})")  # noqa: T201
    for o in offsets:
        print(f"  {rec_day:02d}:00 UTC -> {(rec_day + o) % 24:02d}:00 local (offset {o:+d})")  # noqa: T201
        print(f"  {rec_night:02d}:00 UTC -> {(rec_night + o) % 24:02d}:00 local (offset {o:+d})")  # noqa: T201


def cron_band_value(tz: ZoneInfo, sunrise: int, sunset: int, start_year: int, years: int) -> str:
    """Compact single-line form written to GITHUB_OUTPUT (newline-safe)."""
    offsets = zone_offsets(tz, start_year, years)
    day = cron_candidates(offsets, sunrise, sunset, want_day=True)
    night = cron_candidates(offsets, sunrise, sunset, want_day=False)
    return f"sunrise_utc={day}|sunset_utc={night}"


def write_output(path: str, key: str, value: str) -> None:
    if not path:
        print(f"{key}={value}")  # noqa: T201
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--values-file", required=True)
    parser.add_argument("--key", default="minReplicas")
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--sunrise", required=True)
    parser.add_argument("--sunset", required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--night", required=True)
    parser.add_argument("--sunday-rest", default="false")
    parser.add_argument("--override", default="")
    parser.add_argument("--commit-prefix", default="chore(prod)")
    parser.add_argument("--event", default="")
    parser.add_argument("--now-utc", default="", help="ISO 8601 UTC override for testing/dry runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="", help="GITHUB_OUTPUT file to append results to")
    parser.add_argument("--print-cron-band", action="store_true")
    parser.add_argument("--band-start-year", type=int, default=2026)
    parser.add_argument("--band-years", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    tz_name = args.timezone
    tz = load_timezone(tz_name)
    sunrise = parse_hour(args.sunrise, "sunrise_hour")
    sunset = parse_hour(args.sunset, "sunset_hour")
    day = parse_replicas(args.day, "daytime_min_replicas")
    night = parse_replicas(args.night, "nighttime_min_replicas")
    sunday_rest = parse_bool(args.sunday_rest, "sunday_rest")
    override = parse_replicas(args.override, "min_replicas") if args.override else None

    if args.print_cron_band:
        print_cron_band(tz, tz_name, sunrise, sunset, args.band_start_year, args.band_years)
        return

    now_utc: datetime
    if args.now_utc:
        try:
            now_utc = datetime.fromisoformat(args.now_utc).astimezone(UTC)
        except ValueError:
            fail(f"--now-utc must be ISO 8601, got {args.now_utc!r}")
    else:
        now_utc = datetime.now(UTC)
    now_local = now_utc.astimezone(tz)

    value, decision = decide(now_local, sunrise, sunset, sunday_rest, override, day, night)
    changed, current = update_values_file(args.values_file, args.key, value, args.dry_run)

    commit_message = build_commit_message(args.commit_prefix, args.key, value, decision, args.event)
    weekday = WEEKDAY_NAMES[now_local.weekday()]
    local_iso = now_local.isoformat()
    offset = format_offset(now_local)
    print(f"Decision: {decision} (local {local_iso}, {offset}, {weekday})")  # noqa: T201
    print(f"{args.key}: {current} -> {value} (changed={changed}, dry_run={args.dry_run})")  # noqa: T201
    print(f"Commit message: {commit_message}")  # noqa: T201

    write_output(args.output, "decision", decision)
    write_output(args.output, "resolved_min_replicas", str(value))
    write_output(args.output, "local_time", now_local.isoformat(timespec="seconds"))
    write_output(args.output, "utc_offset", offset)
    write_output(args.output, "weekday", weekday)
    write_output(args.output, "commit_msg", commit_message)
    write_output(args.output, "changed", "true" if changed and not args.dry_run else "false")
    write_output(args.output, "cron_band", cron_band_value(tz, sunrise, sunset, args.band_start_year, args.band_years))


if __name__ == "__main__":
    main(sys.argv[1:])
