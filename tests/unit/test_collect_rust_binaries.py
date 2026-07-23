"""Tests for collect-rust-binaries/collect.sh."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "collect-rust-binaries" / "collect.sh"


def _write_exec(path: Path, body: bytes = b"\x7fELFfake") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_collects_debug_and_release_bins(tmp_path: Path) -> None:
    target = tmp_path / "target"
    out = tmp_path / "build_artifacts"
    _write_exec(target / "debug" / "myapp")
    _write_exec(target / "release" / "myapp")
    # Noise that must be ignored
    (target / "debug" / "myapp.d").write_text("dep")
    (target / "debug" / "libmyapp.rlib").write_bytes(b"rlib")
    _write_exec(target / "debug" / "deps" / "myapp-hash")
    (target / "release" / "incremental").mkdir(parents=True)

    subprocess.run(
        ["bash", str(SCRIPT), str(target), str(out)],
        check=True,
        env={**os.environ, "GITHUB_WORKSPACE": str(tmp_path)},
    )

    assert (out / "debug" / "myapp").is_file()
    assert (out / "release" / "myapp").is_file()
    assert not (out / "debug" / "deps").exists()
    assert not (out / "debug" / "myapp.d").exists()
    assert not (out / "debug" / "libmyapp.rlib").exists()
    manifest = (out / "manifest.txt").read_text()
    assert "debug/myapp" in manifest
    assert "release/myapp" in manifest


def test_missing_target_is_ok(tmp_path: Path) -> None:
    out = tmp_path / "build_artifacts"
    subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path / "missing"), str(out)],
        check=True,
    )
    assert out.is_dir()
