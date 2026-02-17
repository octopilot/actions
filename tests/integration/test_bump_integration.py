import os
import shutil
import subprocess
import sys
import pytest
from pathlib import Path

# Path to the script under test
BUMP_SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../bump-version/bump_version.py'))

def run_bump_action(cwd, mode, bump, file_path=None):
    env = os.environ.copy()
    env["INPUT_MODE"] = mode
    env["INPUT_BUMP"] = bump
    if file_path:
        env["INPUT_FILE"] = str(file_path)
    
    # Capture output for debugging
    result = subprocess.run(
        [sys.executable, BUMP_SCRIPT],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True
    )
    return result

@pytest.fixture
def workspace(tmp_path):
    """Fixture to provide a clean workspace directory."""
    return tmp_path

def test_integration_go_default(workspace):
    # Setup
    tgt = workspace / "internal/cmd"
    tgt.mkdir(parents=True)
    f = tgt / "version.go"
    f.write_text('package cmd\n\nvar Version = "0.1.0"\n', encoding="utf-8")
    
    # Run
    res = run_bump_action(workspace, "go", "patch")
    
    assert res.returncode == 0
    assert 'package cmd\n\nvar Version = "0.1.1"\n' == f.read_text(encoding="utf-8")

def test_integration_go_custom_file(workspace):
    f = workspace / "main.go"
    f.write_text('var Version = "1.0.0"', encoding="utf-8")
    
    res = run_bump_action(workspace, "go", "minor", file_path="main.go")
    
    assert res.returncode == 0
    assert 'var Version = "1.1.0"' == f.read_text(encoding="utf-8")

def test_integration_rust_workspace(workspace):
    # Create workspace layout
    (workspace / "Cargo.toml").write_text('[workspace]\nmembers=["a"]\n[workspace.package]\nversion="0.1.0"', encoding="utf-8")
    (workspace / "a").mkdir()
    (workspace / "a/Cargo.toml").write_text('[package]\nname="a"\nversion="0.1.0"\n[dependencies]\nfoo="1.0"', encoding="utf-8")
    
    res = run_bump_action(workspace, "rust", "minor")
    
    assert res.returncode == 0
    assert 'version="0.2.0"' in (workspace / "Cargo.toml").read_text(encoding="utf-8")
    assert 'version="0.2.0"' in (workspace / "a/Cargo.toml").read_text(encoding="utf-8")

def test_integration_maven_pom(workspace):
    f = workspace / "pom.xml"
    content = """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>app</artifactId>
  <version>1.0.0</version>
</project>"""
    f.write_text(content, encoding="utf-8")
    
    res = run_bump_action(workspace, "maven", "patch")
    
    assert res.returncode == 0
    assert '<version>1.0.1</version>' in f.read_text(encoding="utf-8")

def test_integration_gradle_properties(workspace):
    f = workspace / "gradle.properties"
    f.write_text("version=1.2.3", encoding="utf-8")
    
    res = run_bump_action(workspace, "gradle", "major")
    
    assert res.returncode == 0
    assert "version=2.0.0" == f.read_text(encoding="utf-8")

def test_integration_gradle_build(workspace):
    f = workspace / "build.gradle"
    f.write_text("version = '0.0.1'", encoding="utf-8")
    
    # Auto-detect should pick up build.gradle if gradle.properties is missing
    res = run_bump_action(workspace, "gradle", "patch")
    
    assert res.returncode == 0
    assert "version = '0.0.2'" == f.read_text(encoding="utf-8")

def test_integration_invalid_bump_type(workspace):
    tgt = workspace / "internal/cmd"
    tgt.mkdir(parents=True)
    f = tgt / "version.go"
    f.write_text('package cmd\n\nvar Version = "0.1.0"\n', encoding="utf-8")

    res = run_bump_action(workspace, "go", "unknown")
    
    assert res.returncode != 0
    assert "Unknown bump type" in res.stderr
