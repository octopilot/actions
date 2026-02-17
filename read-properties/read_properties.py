import os
import sys
from contextlib import nullcontext


def read_properties():
    file_path = os.environ.get("INPUT_FILE", "")

    if not file_path:
        print("Error: Input file is required.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Reading properties from {file_path}...")

    github_env = os.environ.get("GITHUB_ENV", "")
    if not github_env:
        print(
            "Warning: GITHUB_ENV not set. Variables will not be exported to workflow environment.",
            file=sys.stderr,
        )

    try:
        with open(file_path) as f:
            lines = f.readlines()

        # If github_env is empty, use stdout/dummy, but logic below handles 'if github_env'
        with open(github_env, "a") if github_env else nullcontext(sys.stdout) as output_file:
            for line in lines:
                line = line.strip()
                # Ignore comments and empty lines
                if not line or line.startswith("#") or line.startswith("!"):
                    continue

                # Split on first '=' or ':'
                if "=" in line:
                    key, value = line.split("=", 1)
                elif ":" in line:
                    key, value = line.split(":", 1)
                else:
                    continue

                key = key.strip()
                value = value.strip()

                if github_env:
                    # Handle multiline if needed, but properties are usually single line
                    # For simplicity, we assume single line values for now, or use EOF delimiter for safety
                    delimiter = "EOF"
                    output_file.write(f"{key}<<{delimiter}\n")
                    output_file.write(f"{value}\n")
                    output_file.write(f"{delimiter}\n")
                else:
                    print(f"{key}={value}")

            if not github_env:
                print("Properties exported successfully.")

    except Exception as e:
        print(f"Error reading properties file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    read_properties()
