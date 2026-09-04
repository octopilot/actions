"""Tests for scale-min-replicas/resolve_scale.py — decision logic, values-file
update, and DST-safe cron band computation.

Dates: September 2026 uses CEST (+02:00) in Europe/Berlin until the last
Sunday of the month (Oct 25), so 2026-09-03 (Thu) is summer time and
2026-01-01 (Thu) is winter time.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scale-min-replicas"))

import resolve_scale as rs

SCRIPT = Path(__file__).resolve().parents[2] / "scale-min-replicas" / "resolve_scale.py"

VALUES = """\
controller:
  image:
    repository: example/app
    tag: "1.2.3"
  replicaCount: 1
  minReplicas: 1  # night default
  maxReplicas: 8
resources:
  limits:
    memory: "512Mi"
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "values.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _read(path: Path) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _now(year: int, month: int, day: int, hour_utc: int = 12) -> datetime:
    return datetime(year, month, day, hour_utc, tzinfo=UTC).astimezone(rs.ZoneInfo("Europe/Berlin"))


# --- in_day_window ---


@pytest.mark.parametrize(
    "hour, sunrise, sunset, expected",
    [
        (7, 8, 20, False),
        (8, 8, 20, True),
        (12, 8, 20, True),
        (19, 8, 20, True),
        (20, 8, 20, False),
        (3, 8, 20, False),
        (23, 8, 20, False),
        # wrap-around window 22:00-06:00
        (21, 22, 6, False),
        (22, 22, 6, True),
        (0, 22, 6, True),
        (5, 22, 6, True),
        (6, 22, 6, False),
        (12, 22, 6, False),
        # degenerate: sunrise == sunset -> never in window
        (8, 8, 8, False),
    ],
)
def test_in_day_window(hour: int, sunrise: int, sunset: int, expected: bool) -> None:
    assert rs.in_day_window(hour, sunrise, sunset) is expected


# --- decide ---


def test_decide_daytime_saturday():
    # 2026-09-05 is Saturday; 10:00 UTC -> 12:00 local, in 8-20 window.
    value, decision = rs.decide(_now(2026, 9, 5), 8, 20, sunday_rest=False, override=None, day=3, night=1)
    assert (value, decision) == (3, "daytime")


def test_decide_nighttime_evening():
    # 2026-09-05 23:00 UTC -> 01:00 local next day (night).
    value, decision = rs.decide(_now(2026, 9, 5, hour_utc=23), 8, 20, sunday_rest=False, override=None, day=3, night=1)
    assert (value, decision) == (1, "nighttime")


def test_decide_sunday_rest_holds_night_even_in_day_window():
    # 2026-09-06 is Sunday; 10:00 UTC -> 12:00 local (would be daytime) but
    # sunday_rest forces the nighttime value.
    value, decision = rs.decide(_now(2026, 9, 6), 8, 20, sunday_rest=True, override=None, day=3, night=1)
    assert (value, decision) == (1, "sunday-rest")


def test_decide_sunday_rest_disabled_allows_sunday_daytime():
    value, decision = rs.decide(_now(2026, 9, 6), 8, 20, sunday_rest=False, override=None, day=3, night=1)
    assert (value, decision) == (3, "daytime")


def test_decide_saturday_night_spilling_into_sunday():
    # 2026-09-05 (Sat) 23:00 UTC -> Sunday 01:00 local: it IS Sunday now,
    # so sunday_rest applies (value is night either way).
    value, decision = rs.decide(_now(2026, 9, 5, hour_utc=23), 8, 20, sunday_rest=True, override=None, day=3, night=1)
    assert (value, decision) == (1, "sunday-rest")


@pytest.mark.parametrize(
    "override, expected_decision",
    [
        ("3", "daytime"),
        ("1", "nighttime"),
        ("7", "explicit"),
        ("0", "explicit"),
    ],
)
def test_decide_override_wins_over_everything(override: str, expected_decision: str) -> None:
    # Sunday 10:00 UTC -> 12:00 local — would be sunday-rest without the override.
    value, decision = rs.decide(_now(2026, 9, 6), 8, 20, sunday_rest=True, override=int(override), day=3, night=1)
    assert value == int(override)
    assert decision == expected_decision


def test_decide_dst_winter_fire_exactly_at_sunrise():
    # 2026-01-01 (Thu) 07:00 UTC -> 08:00 CET (winter, +1): in window.
    value, decision = rs.decide(_now(2026, 1, 1, hour_utc=7), 8, 20, sunday_rest=False, override=None, day=3, night=1)
    assert (value, decision) == (3, "daytime")


def test_decide_dst_summer_fire_one_hour_later_still_in_window():
    # 2026-09-03 (Thu) 07:00 UTC -> 09:00 CEST (summer, +2): in window.
    value, decision = rs.decide(_now(2026, 9, 3, hour_utc=7), 8, 20, sunday_rest=False, override=None, day=3, night=1)
    assert (value, decision) == (3, "daytime")


def test_decide_night_fire_is_night_in_both_seasons():
    # 23:00 UTC: 00:00 CET winter / 01:00 CEST summer — night in both.
    for local in (_now(2026, 1, 1, hour_utc=23), _now(2026, 9, 3, hour_utc=23)):
        value, decision = rs.decide(local, 8, 20, sunday_rest=False, override=None, day=3, night=1)
        assert (value, decision) == (1, "nighttime")


# --- update_values_file ---


def test_update_values_changes_value_preserves_comment_and_indent(tmp_path: Path):
    path = _write(tmp_path, VALUES)
    changed, current = rs.update_values_file(str(path), "minReplicas", 3, dry_run=False)
    assert changed is True
    assert current == 1
    text = _read(path)
    assert "  minReplicas: 3  # night default" in text
    assert "  maxReplicas: 8" in text
    assert "  replicaCount: 1" in text


def test_update_values_noop_when_already_target(tmp_path: Path):
    path = _write(tmp_path, VALUES)
    changed, current = rs.update_values_file(str(path), "minReplicas", 1, dry_run=False)
    assert changed is False
    assert current == 1
    assert _read(path) == VALUES


def test_update_values_dry_run_does_not_touch_file(tmp_path: Path):
    path = _write(tmp_path, VALUES)
    changed, _ = rs.update_values_file(str(path), "minReplicas", 3, dry_run=True)
    assert changed is True
    assert _read(path) == VALUES


def test_update_values_missing_key_fails(tmp_path: Path):
    path = _write(tmp_path, VALUES)
    with pytest.raises(SystemExit):
        rs.update_values_file(str(path), "doesNotExist", 3, dry_run=False)


def test_update_values_ambiguous_key_fails(tmp_path: Path):
    path = _write(tmp_path, "a:\n  minReplicas: 1\nb:\n  minReplicas: 1\n")
    with pytest.raises(SystemExit):
        rs.update_values_file(str(path), "minReplicas", 3, dry_run=False)


def test_update_values_any_indentation(tmp_path: Path):
    path = _write(tmp_path, "deeply:\n      nested:\n          minReplicas: 1\n")
    changed, _ = rs.update_values_file(str(path), "minReplicas", 2, dry_run=False)
    assert changed is True
    assert "          minReplicas: 2" in _read(path)


# --- format_offset ---


def test_format_offset():
    assert rs.format_offset(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))) == "+01:00"
    assert rs.format_offset(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-5)))) == "-05:00"
    assert rs.format_offset(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))) == "+05:30"


# --- commit messages ---


def test_commit_message_schedule_daytime():
    msg = rs.build_commit_message("chore(prod)", "minReplicas", 3, "daytime", "schedule")
    assert msg == "chore(prod): Sunrise - set minReplicas to 3 (cron)"


def test_commit_message_dispatch_nighttime():
    msg = rs.build_commit_message("chore(prod)", "minReplicas", 1, "nighttime", "workflow_dispatch")
    assert msg == "chore(prod): Sunset - set minReplicas to 1 (dispatch)"


def test_commit_message_sunday_rest():
    msg = rs.build_commit_message("chore(prod)", "minReplicas", 1, "sunday-rest", "schedule")
    assert msg == "chore(prod): Sunday rest - hold minReplicas to 1 (cron)"


# --- cron band ---


def test_cron_band_berlin_8_20():
    tz = rs.ZoneInfo("Europe/Berlin")
    offsets = rs.zone_offsets(tz, 2026, 2)
    assert offsets == [1, 2]
    day = rs.cron_candidates(offsets, 8, 20, want_day=True)
    night = rs.cron_candidates(offsets, 8, 20, want_day=False)
    # Day: h with h+1 and h+2 both in [8,20) -> h in [7, 17].
    assert day == list(range(7, 18))
    # Night: h with h+1 and h+2 both outside [8,20) -> h in [0,5] U [19,23].
    assert night == [0, 1, 2, 3, 4, 5, 19, 20, 21, 22, 23]
    # Hours 6 and 18 are ambiguous (DST shift crosses the boundary) -> unsafe
    # for both decisions, excluded from both bands.
    assert 6 not in day and 6 not in night
    assert 18 not in day and 18 not in night
    assert rs.recommended(day, 7) == 7
    # Sunset preference: 20 - max_offset(2) = 18, nearest safe = 19.
    assert rs.recommended(night, 18) == 19


def test_cron_band_wrap_window():
    offsets = [1, 2]
    # Window 22:00-06:00 (in-window local: 22,23,0,1,2,3,4,5). day = h with
    # h+1 AND h+2 both in-window -> h in {21,22,23,0,1,2,3}. night = h with
    # both out-of-window -> h in [5,19]. h=4 (5 in / 6 out) and h=20
    # (21 out / 22 in) straddle the DST shift -> in neither band.
    day = rs.cron_candidates(offsets, 22, 6, want_day=True)
    night = rs.cron_candidates(offsets, 22, 6, want_day=False)
    assert day == [0, 1, 2, 3, 21, 22, 23]
    assert night == list(range(5, 20))
    assert 4 not in day and 4 not in night
    assert 20 not in day and 20 not in night
    assert not set(day) & set(night)
    assert len(day) + len(night) + 2 == 24


def test_cron_band_negative_offsets():
    # America/New_York: -5 winter / -4 summer.
    tz = rs.ZoneInfo("America/New_York")
    offsets = rs.zone_offsets(tz, 2026, 2)
    assert offsets == [-5, -4]
    # Day window 9-17 local: safe UTC hours h with h-5 and h-4 both in [9,17)
    # -> h in [14, 20] (14:00 UTC = 09:00 EST / 10:00 EDT).
    day = rs.cron_candidates(offsets, 9, 17, want_day=True)
    assert day == list(range(14, 21))
    night = rs.cron_candidates(offsets, 9, 17, want_day=False)
    assert night == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 22, 23]
    assert 13 not in day and 13 not in night
    assert 21 not in day and 21 not in night
    assert not set(day) & set(night)


def test_cron_band_no_safe_hour_fails():
    with pytest.raises(SystemExit):
        rs.recommended([], 8)


# --- end-to-end via CLI ---


def _run_cli(values_path: Path, out: Path, now_utc: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--values-file",
            str(values_path),
            "--key",
            "minReplicas",
            "--timezone",
            "Europe/Berlin",
            "--sunrise",
            "8",
            "--sunset",
            "20",
            "--day",
            "3",
            "--night",
            "1",
            "--sunday-rest",
            "true",
            "--event",
            "schedule",
            "--now-utc",
            now_utc,
            "--output",
            str(out),
        ],
        check=True,
    )


def test_cli_end_to_end_writes_outputs(tmp_path: Path):
    path = _write(tmp_path, VALUES)
    out = tmp_path / "github_output"
    _run_cli(path, out, "2026-09-03T07:00:00Z")
    assert _read(path).count("minReplicas: 3") == 1
    written = _read(out)
    assert "decision=daytime" in written
    assert "resolved_min_replicas=3" in written
    assert "utc_offset=+02:00" in written
    assert "weekday=Thursday" in written
    assert "changed=true" in written
    assert "commit_msg=chore(prod): Sunrise - set minReplicas to 3 (cron)" in written
    assert "cron_band=sunrise_utc=" in written


def test_cli_end_to_end_sunday_no_change(tmp_path: Path):
    path = _write(tmp_path, VALUES)
    out = tmp_path / "github_output"
    # Sunday 2026-09-06 07:00 UTC -> 09:00 CEST local, sunday_rest -> night (1).
    _run_cli(path, out, "2026-09-06T07:00:00Z")
    assert _read(path) == VALUES
    written = _read(out)
    assert "decision=sunday-rest" in written
    assert "changed=false" in written
