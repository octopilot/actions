import os
import re
import sys
import toml

def bump_version(version, bump_type):
    major, minor, patch = map(int, version.split('.'))
    if bump_type == 'major':
        major += 1
        minor = 0
        patch = 0
    elif bump_type == 'minor':
        minor += 1
        patch = 0
    elif bump_type == 'patch':
        patch += 1
    else:
        raise ValueError(f"Invalid bump type: {bump_type}")
    return f"{major}.{minor}.{patch}"

def handle_go(file_path, bump_type):
    if not os.path.exists(file_path):
        print(f"Error: Go version file '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Format: var Version = "0.1.0"
    match = re.search(r'var Version = "(.*?)"', content)
    if not match:
        print(f"Error: Could not find version string in {file_path}", file=sys.stderr)
        sys.exit(1)
        
    current_version = match.group(1)
    new_version = bump_version(current_version, bump_type)
    
    new_content = content.replace(f'var Version = "{current_version}"', f'var Version = "{new_version}"')
    
    with open(file_path, 'w') as f:
        f.write(new_content)
        
    return current_version, new_version

def handle_rust(file_path, bump_type):
    if not os.path.exists(file_path):
        print(f"Error: Cargo.toml file '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
        
    data = toml.load(file_path)
    if 'package' not in data or 'version' not in data['package']:
        print(f"Error: Could not find package version in {file_path}", file=sys.stderr)
        sys.exit(1)
        
    current_version = data['package']['version']
    # Handle potential pre-release suffix simply for now, assuming standard semver
    if '-' in current_version:
        current_version = current_version.split('-')[0]
        
    new_version = bump_version(current_version, bump_type)
    
    # Update TOML - using string replacement to preserve comments/formatting
    # toml library might reformat properly, but simple replace covers most cases safely for top-level package version
    # Searching specifically for version = "x.y.z" in [package] section is tricky with simple replace.
    # Let's try partial read or regex. Cargo.toml usually puts version near the top.
    
    with open(file_path, 'r') as f:
        content = f.read()

    # Regex to match version = "x.y.z" inside [package] block is hard with just regex.
    # Assuming standard format: version = "0.1.0"
    # We replace the first occurrence which is usually package version.
    
    pattern = f'version = "{current_version}"'
    if pattern not in content:
         # Try with single quotes
        pattern = f"version = '{current_version}'"
        if pattern not in content:
             print(f"Error: Could not find specific version string '{pattern}' in {file_path}", file=sys.stderr)
             sys.exit(1)

    new_content = content.replace(pattern, f'version = "{new_version}"', 1)
    
    with open(file_path, 'w') as f:
        f.write(new_content)
        
    return current_version, new_version

def main():
    language = os.environ.get("INPUT_MODE", "go")
    bump_type = os.environ.get("INPUT_BUMP", "patch")
    file_path = os.environ.get("INPUT_FILE", "")
    
    if not file_path:
        if language == "go":
            file_path = "internal/cmd/version.go"
        elif language == "rust":
            file_path = "Cargo.toml"

    print(f"Bumping {language} version in {file_path} ({bump_type})...")
    
    if language == "go":
        old, new = handle_go(file_path, bump_type)
    elif language == "rust":
        old, new = handle_rust(file_path, bump_type)
    else:
        print(f"Error: Unsupported mode '{language}'", file=sys.stderr)
        sys.exit(1)
        
    print(f"Bumped from {old} to {new}")
    
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"old_version={old}\n")
            f.write(f"version={new}\n")

if __name__ == "__main__":
    main()
