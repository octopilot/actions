from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Sections that define a package/workspace version we own (not [dependencies]).
VERSION_SECTIONS = ("package", "workspace.package")

# Directory names to skip when walking for Cargo.toml.
SKIP_PARTS = (
    "target",
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "node_packages",
    "build",
    "dist",
    "tmp",
)

def bump_semver(old: str, bump: str) -> str:
    """Compute next version from old (X.Y.Z or X.Y.Z-rc.N or v-prefixed) and bump.
    
    Supported bumps: major, minor, patch, rc, release.
    """
    old = old.lstrip("v")
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([\w.-]+))?$", old)
    if not m:
        print(f"Error: Invalid version format: {old}", file=sys.stderr)
        sys.exit(1)

    x, y, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
    prerel = m.group(4)  # None or e.g. "rc.2"

    b = (bump or "patch").lower()

    if b == "rc":
        if not prerel:
            return f"{x}.{y}.{z}-rc.1"
        m2 = re.match(r"^rc\.(\d+)$", prerel)
        if not m2:
            print(f"Error: rc bump only supports -rc.N prerelease; found -{prerel}", file=sys.stderr)
            sys.exit(1)
        return f"{x}.{y}.{z}-rc.{int(m2.group(1)) + 1}"

    if b in ("release", "promote"):
        if not prerel:
            print(f"Error: Already a full release ({old}). Use patch, minor, or major to create a new version.", file=sys.stderr)
            sys.exit(1)
        return f"{x}.{y}.{z}"

    if b == "patch":
        z += 1
    elif b == "minor":
        y += 1
        z = 0
    elif b == "major":
        x += 1
        y = z = 0
    else:
        print(f"Error: Unknown bump type: {bump}", file=sys.stderr)
        sys.exit(1)
        
    return f"{x}.{y}.{z}"

def get_current_version_go(content: str) -> str:
    # Format: var Version = "0.1.0"
    match = re.search(r'var Version = "(.*?)"', content)
    if not match:
        raise ValueError("Could not find 'var Version' string")
    return match.group(1)

def get_current_version_rust(content: str) -> str:
    # Look for [package] or [workspace.package] followed by version = "..."
    # This is a heuristic. For source of truth, we expect it in the [package] or [workspace.package] section.
    # We will iterate lines to be safe.
    lines = content.splitlines()
    in_sec = False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            in_sec = s.strip("[]").strip() in VERSION_SECTIONS
            continue
        if in_sec:
            m = re.match(r'^\s*version\s*=\s*"v?(\d+\.\d+\.\d+(?:-[\w.-]+)?)"', line)
            if m:
                return m.group(1)
    raise ValueError("Could not find [package] version")

def replace_version_in_file(path: Path, old: str, new: str, mode: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return False
        
    if mode == "go":
        # Simple replacement for Go
        new_content = text.replace(f'var Version = "{old}"', f'var Version = "{new}"')
        if text != new_content:
            path.write_text(new_content, encoding="utf-8")
            return True
        return False

    elif mode == "rust":
        # Regex replacement for Rust [package] logic
        lines = text.splitlines(keepends=True)
        out = []
        in_sec = False
        replaced = False
        for line in lines:
            s = line.strip()
            if s.startswith("["):
                in_sec = s.strip("[]").strip() in VERSION_SECTIONS
                out.append(line)
                continue
            if in_sec:
                # Match version = "old" or "vold"
                pat = r'(\s*version\s*=\s*")v?' + re.escape(old) + r'"'
                if re.search(pat, line):
                    new_line = re.sub(pat, lambda m: m.group(1) + new + '"', line, count=1)
                    out.append(new_line)
                    replaced = True
                    continue
            out.append(line)
        
        if replaced:
            path.write_text("".join(out), encoding="utf-8")
        return replaced
        
    return False

def get_current_version_maven(content: str) -> str:
    # Match <version>...</version> inside <project>...<version>...</version>...</project>
    # Simple regex approach: find the first <version> tag that is NOT inside a <dependency>, <parent>, or <plugin>.
    # However, standard practice is <project>...<version>X.Y.Z</version>...
    # We will look for <version> at the top level of project.
    # A safe heuristic for simple poms: The project version is usually the first <version> tag, 
    # unless there is a <parent> tag. If there is a parent, the project version might be inherited (no version tag)
    # or explicitly defined.
    # To be robust without full XML parsing (which destroys formatting), we search for:
    # <version>X.Y.Z</version> that is NOT indented more than the project tag (roughly).
    # Actually, a better heuristic used by tools: <project> ... <version>...</version>
    # We'll search for <version>...</version> and check if it looks like the main version.
    
    # Strategy:
    # 1. Look for <version> after <artifactId> but before <dependencies>, <build>, <profiles> etc.
    # 2. Or just find matches and return the first one that is a SemVer.
    # Let's try to match <version>X.Y.Z</version> taking indentation into account? No, XML is free-form.
    
    # Refined Strategy:
    # Look for <version> match. Ignore if it follows <parent>.
    # Keep it simple for now: We assume standard Maven layout where project version is 
    # early in the file, possibly after <parent> (if inheriting) or standalone.
    # Wait, if <parent> exists, the project might NOT have a version.
    # We will look for <version> with regex.
    
    matches = list(re.finditer(r'<version>(.*?)</version>', content))
    if not matches:
        raise ValueError("Could not find <version> tag in pom.xml")
    
    # Filter out potential parent/dependency versions?
    # Usually the project version is defined near top.
    # If <parent> exists, the first version tag might be parent's version.
    if '<parent>' in content:
         # If parent block ends before our match, then our match is likely project version.
         # Or if match is inside parent block.
         # This regex approach is fragile for complex XML.
         # Let's try to find <project> ... <version>
         pass
         
    # Fallback to first match for MVP, user can provide specific file path if needed.
    # Actually, let's look at the indentation?
    # Or just assume the standard convention.
    return matches[0].group(1)

def get_current_version_gradle(content: str, filename: str) -> str:
    # gradle.properties: version=1.2.3
    if filename.endswith(".properties"):
        match = re.search(r'^version\s*=\s*(.*?)\s*$', content, re.MULTILINE)
        if match:
            return match.group(1)
            
    # build.gradle / build.gradle.kts: version = '1.2.3' or version '1.2.3'
    else:
        # version = "..." or version = '...'
        match = re.search(r'''version\s*=?\s*["'](.*?)["']''', content)
        if match:
             return match.group(1)
             
    raise ValueError(f"Could not find version in {filename}")

def replace_version_in_file_maven(path: Path, old: str, new: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return False
        
    # Replace <version>old</version> -> <version>new</version>
    # We replace the *first* matching occurrence of the OLD version in a version tag.
    # This assumes we want to update the one we found earlier.
    pat = r'(<version>)' + re.escape(old) + r'(</version>)'
    if re.search(pat, text):
        new_content = re.sub(pat, lambda m: m.group(1) + new + m.group(2), text, count=1)
        if text != new_content:
            path.write_text(new_content, encoding="utf-8")
            return True
    return False

def replace_version_in_file_gradle(path: Path, old: str, new: str, filename: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return False
        
    if filename.endswith(".properties"):
         # version=old
         pat = r'^(version\s*=\s*)' + re.escape(old) + r'(\s*)$'
         new_content = re.sub(pat, lambda m: m.group(1) + new + m.group(2), text, count=1, flags=re.MULTILINE)
    else:
         # available patterns: version = 'old', version 'old', version = "old", version "old"
         pat = r'''(version\s*=?\s*["'])''' + re.escape(old) + r'''(["'])'''
         new_content = re.sub(pat, lambda m: m.group(1) + new + m.group(2), text, count=1)
         
    if text != new_content:
        path.write_text(new_content, encoding="utf-8")
        return True
    return False

def _cargo_toml_paths(project_root: Path) -> list[Path]:
    out = []
    # Use Path.rglob which is available in Python 3.12 (action uses 3.12)
    # We need to manually filter skip parts
    for p in project_root.rglob("Cargo.toml"):
        try:
            rel = p.relative_to(project_root)
        except ValueError:
            continue
        if any(part in rel.parts for part in SKIP_PARTS):
            continue
        if p.is_file():
            out.append(p)
    return sorted(out)

def main():
    mode = os.environ.get("INPUT_MODE", "go")
    bump_type = os.environ.get("INPUT_BUMP", "patch")
    file_path_str = os.environ.get("INPUT_FILE", "")
    
    if not file_path_str:
        if mode == "go":
            file_path_str = "internal/cmd/version.go"
        elif mode == "rust":
            file_path_str = "Cargo.toml"
        elif mode == "maven":
            file_path_str = "pom.xml"
        elif mode == "gradle":
            if os.path.exists("gradle.properties"):
                file_path_str = "gradle.properties"
            else:
                # Default to build.gradle, user can override to build.gradle.kts
                if os.path.exists("build.gradle.kts"):
                     file_path_str = "build.gradle.kts"
                else:
                     file_path_str = "build.gradle"
            
    file_path = Path(file_path_str)
    if not file_path.is_file():
        # Only error if we expect it to exist. For gradle auto-detect we might fail.
        print(f"Error: Version file '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
        
    print(f"Reading current version from {file_path}...")
    content = file_path.read_text(encoding="utf-8")
    
    try:
        if mode == "go":
            current_version = get_current_version_go(content)
        elif mode == "rust":
            current_version = get_current_version_rust(content)
        elif mode == "maven":
            current_version = get_current_version_maven(content)
        elif mode == "gradle":
            current_version = get_current_version_gradle(content, file_path.name)
        else:
            print(f"Error: Unsupported mode '{mode}'", file=sys.stderr)
            sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    print(f"Current version: {current_version}")
    
    new_version = bump_semver(current_version, bump_type)
    print(f"Target version: {new_version} ({bump_type})")
    
    updated_files = []
    
    if mode == "go":
        if replace_version_in_file(file_path, current_version, new_version, mode):
            updated_files.append(file_path)
    elif mode == "maven":
        if replace_version_in_file_maven(file_path, current_version, new_version):
             updated_files.append(file_path)
    elif mode == "gradle":
        if replace_version_in_file_gradle(file_path, current_version, new_version, file_path.name):
             updated_files.append(file_path)
    elif mode == "rust":
        # For Rust, we walk the whole workspace
        project_root = Path.cwd()
        # First ensure we update the source of truth file
        if replace_version_in_file(file_path, current_version, new_version, mode):
             updated_files.append(file_path)

        # Then walk others
        print(f"Scanning workspace for Cargo.toml files to update...")
        for p in _cargo_toml_paths(project_root):
             if p.resolve() == file_path.resolve():
                 continue # Already processed
             
             if replace_version_in_file(p, current_version, new_version, mode):
                 updated_files.append(p)
                 
    if not updated_files:
        print("Warning: No files were updated.", file=sys.stderr)
    else:
        print(f"Updated {len(updated_files)} files:")
        for p in updated_files:
            print(f"  {p}")
            
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"old_version={current_version}\n")
            f.write(f"version={new_version}\n")

if __name__ == "__main__":
    main()
