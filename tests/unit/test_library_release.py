"""Tests for library-release/release.py (version choice, changelog grouping, note sanitising)."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "library-release" / "release.py"
_spec = importlib.util.spec_from_file_location("library_release", _PATH)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


def v(s):
    return lr.parse(s)


@pytest.mark.parametrize(
    ("tags", "cargo", "kind", "explicit", "want"),
    [
        ({}, v("0.1.0"), "patch", "", "0.1.0"),  # first release: the manifest's version
        ({}, v("0.1.0-alpha.1"), "patch", "", "0.1.0"),  # ... without its prerelease suffix
        ({"v0.1.2": v("0.1.2")}, v("0.1.1"), "patch", "", "0.1.3"),  # tag above the manifest
        ({"v0.1.12": v("0.1.12")}, v("0.1.11"), "minor", "", "0.2.0"),
        ({"v0.1.0": v("0.1.0")}, v("0.3.0"), "patch", "", "0.3.1"),  # manifest above the tags
        ({"v1.2.0-rc.1": v("1.2.0-rc.1")}, None, "patch", "", "1.2.0"),
        ({"v0.1.0": v("0.1.0")}, v("0.1.0"), "major", "", "1.0.0"),
        ({"v0.1.0": v("0.1.0")}, v("0.1.0"), "patch", "0.4.0", "0.4.0"),
    ],
)
def test_next_version(tags, cargo, kind, explicit, want):
    assert lr.fmt(lr.next_version(tags, cargo, kind, explicit)) == want


def test_key_orders_prereleases_below_release():
    assert lr.key(v("1.0.0-rc.2")) < lr.key(v("1.0.0"))
    assert lr.key(v("1.0.0-rc.2")) < lr.key(v("1.0.0-rc.10"))
    assert lr.key(v("0.9.9")) < lr.key(v("1.0.0-alpha"))


@pytest.mark.parametrize(
    ("subject", "body", "want"),
    [
        ("feat(router): add x", "", "Features"),
        ("feat!: drop y", "", "Breaking changes"),
        ("fix: z", "BREAKING CHANGE: api", "Breaking changes"),
        ("fix(pool): z", "", "Fixes"),
        ("perf: faster", "", "Fixes"),
        ("chore(deps): bump serde", "", "Dependencies"),
        ("Bump serde from 1.0.1 to 1.0.2", "", "Dependencies"),
        ("Add a thing", "", "Features"),
        ("Fix a thing", "", "Fixes"),
        ("docs: readme", "", "Other"),
    ],
)
def test_classify(subject, body, want):
    assert lr.classify(subject, body) == want


def test_sanitise_drops_denied_words_and_empty_sections(monkeypatch):
    monkeypatch.setattr(lr, "DENY_SHA256", {lr.hashlib.sha256(b"acme").hexdigest()})
    text = "### Features\n\n- support Acme pools (abc)\n\n### Fixes\n\n- fix crash (def)\n"
    assert lr.sanitise(text, "org/lib") == "### Fixes\n\n- fix crash (def)\n"


def test_sanitise_allows_words_of_own_repo_name(monkeypatch):
    monkeypatch.setattr(lr, "DENY_SHA256", {lr.hashlib.sha256(b"acme").hexdigest()})
    assert lr.sanitise("- acme client fix\n", "org/acme-client") == "- acme client fix\n"
