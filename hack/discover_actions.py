import json
import os


def main():
    actions = []
    # Walk the current directory
    for root, _, files in os.walk("."):
        # Check for both action.yml and Dockerfile
        if "action.yml" in files and "Dockerfile" in files:
            # Get relative path from root
            path = os.path.relpath(root, ".")

            # Skip the root directory itself if it happens to have these files (unlikely but safe)
            if path == ".":
                continue

            actions.append(path)

    # Sort for deterministic output
    actions.sort()

    print(f"Found containerizable actions: {actions}")

    # Write to GITHUB_OUTPUT
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"actions={json.dumps(actions)}\n")
    else:
        # Fallback for local testing
        print(f"::set-output name=actions::{json.dumps(actions)}")

<<<<<<< HEAD
=======

>>>>>>> 844bcc9 (fix(hack): resolve linting errors in discovery script)
if __name__ == "__main__":
    main()
