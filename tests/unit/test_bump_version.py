import re
import sys
import os
import pytest
from pathlib import Path

# Add bump-version directory to sys.path so we can import bump_version
sys.path.append(os.path.join(os.path.dirname(__file__), '../../bump-version'))

import bump_version

# --- SemVer Logic Tests ---

@pytest.mark.parametrize("old, bump, expected", [
    ("0.1.0", "patch", "0.1.1"),
    ("0.1.0", "minor", "0.2.0"),
    ("0.1.0", "major", "1.0.0"),
    ("0.1.9", "patch", "0.1.10"),
    ("0.1.0", "rc", "0.1.0-rc.1"),
    ("0.1.0-rc.1", "rc", "0.1.0-rc.2"),
    ("0.1.0-rc.9", "rc", "0.1.0-rc.10"),
    ("0.1.0-rc.5", "patch", "0.1.1"), # promote and bump
    ("0.1.0-rc.5", "minor", "0.2.0"),
    ("0.1.0-rc.5", "major", "1.0.0"),
    ("0.1.0-rc.5", "release", "0.1.0"),
    ("0.1.0-rc.5", "promote", "0.1.0"),
    ("v0.1.0", "patch", "0.1.1"), # handles v-prefix
])
def test_bump_semver_valid(old, bump, expected):
    assert bump_version.bump_semver(old, bump) == expected

def test_bump_semver_invalid_release():
    with pytest.raises(SystemExit):
        bump_version.bump_semver("0.1.0", "release")  # Already released

def test_bump_semver_invalid_rc():
    with pytest.raises(SystemExit):
        bump_version.bump_semver("0.1.0-beta.1", "rc") # only supports rc.N

def test_bump_semver_invalid_format():
    with pytest.raises(SystemExit):
        bump_version.bump_semver("invalid", "patch")

# --- Go Logic Tests ---

def test_get_current_version_go():
    content = 'package cmd\n\nvar Version = "0.1.0"\n'
    assert bump_version.get_current_version_go(content) == "0.1.0"

def test_get_current_version_go_error():
    content = 'package cmd\n\nconst Version = "0.1.0"\n'
    with pytest.raises(ValueError, match="Could not find 'var Version' string"):
        bump_version.get_current_version_go(content)

def test_replace_version_in_file_go(tmp_path):
    f = tmp_path / "version.go"
    f.write_text('package cmd\n\nvar Version = "0.1.0"\n', encoding="utf-8")
    
    assert bump_version.replace_version_in_file(f, "0.1.0", "0.1.1", "go") is True
    assert f.read_text(encoding="utf-8") == 'package cmd\n\nvar Version = "0.1.1"\n'

# --- Rust Logic Tests ---

def test_get_current_version_rust_package():
    content = '[package]\nname = "foo"\nversion = "0.1.0"\nedition = "2021"\n'
    assert bump_version.get_current_version_rust(content) == "0.1.0"

def test_get_current_version_rust_workspace():
    content = '[workspace.package]\nversion = "0.1.0"\nauthors = ["me"]\n'
    assert bump_version.get_current_version_rust(content) == "0.1.0"

def test_get_current_version_rust_ignore_dependencies():
    content = '[package]\nname="foo"\n\n[dependencies]\nbar = { version = "1.0.0" }\n'
    # Should fail if we don't find package version, but logic assumes valid package/workspace section
    # If no version in package, it raises ValueError
    with pytest.raises(ValueError):
        bump_version.get_current_version_rust(content)

def test_replace_version_in_file_rust_package(tmp_path):
    f = tmp_path / "Cargo.toml"
    content = """[package]
name = "foo"
version = "0.1.0"
edition = "2021"

[dependencies]
bar = "1.0.0"
"""
    f.write_text(content, encoding="utf-8")
    
    assert bump_version.replace_version_in_file(f, "0.1.0", "0.1.1", "rust") is True
    
    new_content = f.read_text(encoding="utf-8")
    assert 'version = "0.1.1"' in new_content
    # Dependencies should be untouched
    assert 'bar = "1.0.0"' in new_content

def test_replace_version_in_file_rust_workspace(tmp_path):
    f = tmp_path / "Cargo.toml"
    content = """[workspace]
members = ["crate-a"]

[workspace.package]
version = "0.1.0"
authors = ["me"]
"""
    f.write_text(content, encoding="utf-8")
    
    assert bump_version.replace_version_in_file(f, "0.1.0", "0.2.0", "rust") is True
    assert 'version = "0.2.0"' in f.read_text(encoding="utf-8")

def test_replace_version_in_file_rust_member_update(tmp_path):
    f = tmp_path / "Cargo.toml"
    content = """[package]
name = "crate-a"
version = "0.1.0"

[dependencies]
foo = { workspace = true }
"""
    f.write_text(content, encoding="utf-8")
    
    # Member should update if it matches old version
    assert bump_version.replace_version_in_file(f, "0.1.0", "0.1.1", "rust") is True
    assert 'version = "0.1.1"' in f.read_text(encoding="utf-8")

def test_replace_version_in_file_rust_member_no_update_mismatch(tmp_path):
    f = tmp_path / "Cargo.toml"
    content = """[package]
name = "crate-b"
version = "0.0.1" # Distinct version
"""
    f.write_text(content, encoding="utf-8")
    
    # Member should NOT update if version differs
    assert bump_version.replace_version_in_file(f, "0.1.0", "0.1.1", "rust") is False
    assert 'version = "0.0.1"' in f.read_text(encoding="utf-8")

# --- Integration / Workspace Scan Logic ---

def test_cargo_toml_paths_filtering(tmp_path):
    # Create valid Cargo.toml
    (tmp_path / "Cargo.toml").touch()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/Cargo.toml").touch()
    
    # Create ignored paths
    (tmp_path / "target").mkdir()
    (tmp_path / "target/Cargo.toml").touch()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/Cargo.toml").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/Cargo.toml").touch()
    
    paths = bump_version._cargo_toml_paths(tmp_path)
    # convert to relative strings for checking
    rel_paths = [str(p.relative_to(tmp_path)) for p in paths]
    
    assert "Cargo.toml" in rel_paths
    assert "sub/Cargo.toml" in rel_paths
    assert "target/Cargo.toml" not in rel_paths
    assert ".git/Cargo.toml" not in rel_paths
    assert "node_modules/Cargo.toml" not in rel_paths

# --- Maven Logic Tests ---

def test_get_current_version_maven():
    # Standard pom
    content = """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
</project>
"""
    assert bump_version.get_current_version_maven(content) == "1.0.0"

def test_get_current_version_maven_indented():
    content = """<project>
    <version>0.9.9</version>
</project>"""
    assert bump_version.get_current_version_maven(content) == "0.9.9"

def test_replace_version_in_file_maven(tmp_path):
    f = tmp_path / "pom.xml"
    content = """<project>
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <dependencies>
      <dependency>
          <groupId>other</groupId>
          <artifactId>lib</artifactId>
          <version>1.0.0</version>
      </dependency>
  </dependencies>
</project>
"""
    f.write_text(content, encoding="utf-8")
    
    assert bump_version.replace_version_in_file_maven(f, "1.0.0", "1.0.1") is True
    
    new_content = f.read_text(encoding="utf-8")
    # Should replace the FIRST occurrence (project version)
    assert '<version>1.0.1</version>' in new_content
    # Dependency version usually appears later, but if it matches old version it MIGHT get replaced if we aren't careful.
    # Our regex logic replaces the FIRST occurrence.
    # In standard POM, project version comes before dependencies.
    # So the dependency version "1.0.0" should remain "1.0.0" if it was distinct, but here it is same.
    # `re.sub(..., count=1)` ensures only the first one found is replaced.
    # Check that dependency is UNCHANGED if it appears after.
    # Python re.sub replaces from left to right.
    
    # We expect 'version>1.0.1<' at the top, and 'version>1.0.0<' inside dependency
    matches = list(re.finditer(r'<version>(.*?)</version>', new_content))
    assert len(matches) >= 2
    assert matches[0].group(1) == "1.0.1" # First one updated
    assert matches[1].group(1) == "1.0.0" # Second one (dependency) untouched

# --- Gradle Logic Tests ---

def test_get_current_version_gradle_properties():
    content = "version=1.2.3\n"
    assert bump_version.get_current_version_gradle(content, "gradle.properties") == "1.2.3"

def test_get_current_version_gradle_build_groovy():
    content = "plugins { id 'java' }\nversion = '0.1.0'\n"
    assert bump_version.get_current_version_gradle(content, "build.gradle") == "0.1.0"

def test_get_current_version_gradle_build_kotlin():
    content = 'version = "0.1.0-rc.1"'
    assert bump_version.get_current_version_gradle(content, "build.gradle.kts") == "0.1.0-rc.1"
    
def test_replace_version_in_file_gradle_properties(tmp_path):
    f = tmp_path / "gradle.properties"
    f.write_text("version=1.2.3\nfoo=bar", encoding="utf-8")
    
    assert bump_version.replace_version_in_file_gradle(f, "1.2.3", "1.2.4", f.name) is True
    assert f.read_text(encoding="utf-8") == "version=1.2.4\nfoo=bar"

def test_replace_version_in_file_gradle_build(tmp_path):
    f = tmp_path / "build.gradle"
    f.write_text("group 'com.example'\nversion = '1.0.0'\n", encoding="utf-8")
    
    assert bump_version.replace_version_in_file_gradle(f, "1.0.0", "1.1.0", f.name) is True
    assert "version = '1.1.0'" in f.read_text(encoding="utf-8")
