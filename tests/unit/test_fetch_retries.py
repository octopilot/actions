"""Retrying downloads: common/fetch.sh, common/install-kind.sh, setup-tools download_file, and the
nextest install command detect-contexts emits.

GitHub release downloads intermittently answered 504 (2026-11-08) and every one-shot download
in the pipeline failed the release build. A fake `curl` on PATH replays a scripted sequence of
HTTP codes; a fake `sleep` makes the backoff instant.
"""

import hashlib
import importlib.util
import os
import stat
import subprocess
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FETCH = ROOT / "common" / "fetch.sh"
INSTALL_KIND = ROOT / "common" / "install-kind.sh"

FAKE_CURL = r"""#!/usr/bin/env bash
# Fake curl: pops the next HTTP code from $FAKE_CURL_SCRIPT (one per line; "conn" = connection
# error), writes $FAKE_CURL_BODY (or the URL-specific body in $FAKE_CURL_BODIES/<basename>)
# to -o on 2xx, prints the code for -w, logs the URL.
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w|--connect-timeout|--max-time|--proto) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
echo "$url" >> "$FAKE_CURL_LOG"
code="$(head -n1 "$FAKE_CURL_SCRIPT")"; sed -i '1d' "$FAKE_CURL_SCRIPT"
[ -n "$code" ] || code=200
if [ "$code" = conn ]; then printf '000'; exit 7; fi
if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
  body="${FAKE_CURL_BODY:-payload}"
  if [ -n "${FAKE_CURL_BODIES:-}" ] && [ -f "$FAKE_CURL_BODIES/$(basename "$url")" ]; then
    cp "$FAKE_CURL_BODIES/$(basename "$url")" "$out"
  else
    printf '%s' "$body" > "$out"
  fi
else
  printf 'error page' > "$out"
fi
printf '%s' "$code"
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def fakebin(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(bindir / "curl", FAKE_CURL)
    _exe(bindir / "sleep", "#!/bin/sh\nexit 0\n")
    log = tmp_path / "curl.log"
    log.touch()
    script = tmp_path / "codes"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_CURL_LOG": str(log),
        "FAKE_CURL_SCRIPT": str(script),
    }
    return env, script, log


def _fetch(env, url, out):
    return subprocess.run(["bash", str(FETCH), url, str(out)], env=env, capture_output=True, text=True)


def test_fetch_retries_5xx_then_succeeds(fakebin, tmp_path):
    env, script, log = fakebin
    script.write_text("504\n502\nconn\n200\n")
    out = tmp_path / "dl" / "kind"
    r = _fetch(env, "https://github.com/x/y/releases/download/v1/kind", out)
    assert r.returncode == 0, r.stderr
    assert out.read_text() == "payload"
    assert not Path(f"{out}.part").exists()
    assert len(log.read_text().splitlines()) == 4
    assert "attempt 1/6 got HTTP 504" in r.stderr


def test_fetch_gives_up_after_attempts_and_leaves_no_file(fakebin, tmp_path):
    env, script, log = fakebin
    script.write_text("504\n" * 10)
    out = tmp_path / "f"
    r = _fetch({**env, "FETCH_ATTEMPTS": "3"}, "https://example.test/f", out)
    assert r.returncode == 1
    assert not out.exists() and not Path(f"{out}.part").exists()
    assert len(log.read_text().splitlines()) == 3
    assert "giving up" in r.stderr


def test_fetch_does_not_retry_hard_4xx(fakebin, tmp_path):
    env, script, log = fakebin
    script.write_text("404\n200\n")
    r = _fetch(env, "https://example.test/missing", tmp_path / "f")
    assert r.returncode == 1
    assert len(log.read_text().splitlines()) == 1
    assert "not retryable" in r.stderr


def test_fetch_retries_429(fakebin, tmp_path):
    env, script, _ = fakebin
    script.write_text("429\n200\n")
    assert _fetch(env, "https://example.test/f", tmp_path / "f").returncode == 0


def test_install_kind_seeds_kind_action_tool_cache(fakebin, tmp_path):
    env, script, log = fakebin
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    kind_bin, kubectl_bin = b"#!/bin/sh\necho kind\n", b"#!/bin/sh\necho 'Client Version: v1.35.0'\n"
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[os.uname().machine]
    (bodies / f"kind-linux-{arch}").write_bytes(kind_bin)
    sha = hashlib.sha256(kind_bin).hexdigest()
    (bodies / f"kind-linux-{arch}.sha256sum").write_text(f"{sha}  kind-linux-{arch}\n")
    (bodies / "kubectl").write_bytes(kubectl_bin)
    (bodies / "kubectl.sha256").write_text(hashlib.sha256(kubectl_bin).hexdigest())
    # a 504 on the first kind download, then everything succeeds
    script.write_text("504\n200\n200\n200\n200\n")
    cache = tmp_path / "toolcache"
    cache.mkdir()
    r = subprocess.run(
        ["bash", str(INSTALL_KIND), "v0.31.0", "v1.35.0"],
        env={**env, "RUNNER_TOOL_CACHE": str(cache), "FAKE_CURL_BODIES": str(bodies)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    base = cache / "kind" / "v0.31.0" / arch
    # the exact paths helm/kind-action@v1 checks before downloading
    assert os.access(base / "kind" / "bin" / "kind", os.X_OK)
    assert os.access(base / "kubectl" / "bin" / "kubectl", os.X_OK)
    urls = log.read_text().splitlines()
    assert urls[0] == urls[1]  # the 504'd kind download was retried
    # second run is a no-op
    log.write_text("")
    r2 = subprocess.run(
        ["bash", str(INSTALL_KIND), "v0.31.0", "v1.35.0"],
        env={**env, "RUNNER_TOOL_CACHE": str(cache)},
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 0, r2.stderr
    assert log.read_text() == ""


def test_install_kind_rejects_bad_checksum(fakebin, tmp_path):
    env, script, _ = fakebin
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}[os.uname().machine]
    (bodies / f"kind-linux-{arch}").write_bytes(b"tampered")
    (bodies / f"kind-linux-{arch}.sha256sum").write_text(f"{'0' * 64}  kind-linux-{arch}\n")
    script.write_text("200\n200\n")
    cache = tmp_path / "toolcache"
    cache.mkdir()
    r = subprocess.run(
        ["bash", str(INSTALL_KIND), "v0.31.0", "v1.35.0"],
        env={**env, "RUNNER_TOOL_CACHE": str(cache), "FAKE_CURL_BODIES": str(bodies)},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert not (cache / "kind" / "v0.31.0" / arch / "kind" / "bin" / "kind").exists()


def _install_tools():
    spec = importlib.util.spec_from_file_location("install_tools", ROOT / "setup-tools" / "install_tools.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_install_tools_download_retries_5xx(tmp_path, monkeypatch):
    mod = _install_tools()
    calls = []

    def fake_retrieve(url, dest):
        calls.append(url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 504, "Gateway Time-out", {}, None)
        Path(dest).write_text("bin")

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", fake_retrieve)
    dest = tmp_path / "sops"
    mod.download_file("https://github.com/x/y/releases/download/v1/sops", str(dest), sleep=lambda s: None)
    assert dest.read_text() == "bin" and len(calls) == 3
    assert not Path(f"{dest}.part").exists()


def test_install_tools_download_does_not_retry_404(tmp_path, monkeypatch):
    mod = _install_tools()
    calls = []

    def fake_retrieve(url, dest):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", fake_retrieve)
    with pytest.raises(SystemExit):
        mod.download_file("https://example.test/missing", str(tmp_path / "x"), sleep=lambda s: None)
    assert len(calls) == 1


def test_nextest_install_downloads_to_file_with_retries():
    """The emitted command must not pipe curl into tar (a retry mid-stream corrupts the archive)."""
    text = (ROOT / "detect-contexts" / "detect.py").read_text()
    assert "get.nexte.st/latest/linux | tar" not in text
    assert "--retry-all-errors" in text and 'nextest.tar.gz" -C "$HOME/.cargo/bin"' in text


@pytest.mark.parametrize(
    "path",
    [
        "test/action.yml",
        "lint/action.yml",
        "sccache/action.yml",
        "promote-registry/action.yml",
        "kotlin-lint/action.yml",
    ],
)
def test_composite_actions_download_through_fetch(path):
    text = (ROOT / path).read_text()
    assert "common/fetch.sh" in text or "common/install-kind.sh" in text
    assert "curl -sSL" not in text and "| tar" not in text


def test_kind_action_is_preseeded_with_matching_versions():
    seeded = [("test/action.yml", "common/install-kind.sh"), (".github/workflows/pipeline.yml", "setup-kind@main")]
    for path, pre in seeded:
        text = (ROOT / path).read_text()
        assert pre in text, path
        assert text.index(pre) < text.index("helm/kind-action@v1"), path
        assert "kubectl_version: v1.35.0" in text, path
