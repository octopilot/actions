import base64
import os
import subprocess
import sys


def setup_keys():
    """Import GPG or AGE keys from environment variables."""
    gpg_key = os.environ.get("INPUT_GPG_KEY")
    age_key = os.environ.get("INPUT_AGE_KEY")

    if gpg_key:
        print("Importing GPG key...")
        try:
            # Decode base64 GPG key
            decoded_key = base64.b64decode(gpg_key)

            # Import into GPG keyring
            subprocess.run(["gpg", "--import"], input=decoded_key, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error importing GPG key: {e.stderr.decode()}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error decoding GPG key: {e}", file=sys.stderr)
            sys.exit(1)

    if age_key:
        print("Setting up AGE key...")
        os.environ["SOPS_AGE_KEY"] = age_key


def decrypt_file():
    """Decrypt the file using SOPS."""
    file_path = os.environ.get("INPUT_FILE")
    output_type = os.environ.get("INPUT_OUTPUT_TYPE", "json")

    if not file_path:
        print("Error: Input file is required.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    cmd = ["sops", "--decrypt"]

    # Handle output format
    if output_type == "json":
        cmd.extend(["--output-type", "json"])
    elif output_type == "yaml":
        cmd.extend(["--output-type", "yaml"])
    elif output_type == "dotenv":
        cmd.extend(["--output-type", "dotenv"])

    cmd.append(file_path)

    try:
        print(f"Decrypting {file_path}...")
        result = subprocess.run(cmd, capture_output=True, check=True, text=True)
        decrypted_data = result.stdout

        # Write to GITHUB_OUTPUT
        if "GITHUB_OUTPUT" in os.environ:
            # Multi-line string handling for GITHUB_OUTPUT
            delimiter = "EOF"
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"data<<{delimiter}\n")
                f.write(decrypted_data)
                f.write(f"\n{delimiter}\n")
        else:
            print(decrypted_data)

        # Handle export_envs
        export_envs = os.environ.get("INPUT_EXPORT_ENVS", "false").lower() == "true"
        if export_envs and "GITHUB_ENV" in os.environ:
            print("Exporting secrets to GITHUB_ENV...")
            env_file = os.environ["GITHUB_ENV"]
            
            if output_type == "dotenv":
                # Dotenv is already KEY=VALUE
                with open(env_file, "a") as f:
                    for line in decrypted_data.splitlines():
                        if line.strip() and not line.strip().startswith("#"):
                            # Simple parsing for dotenv
                            key, value = line.split("=", 1)
                            f.write(f"{key.strip()}={value.strip()}\n")
            
            elif output_type == "json":
                import json
                try:
                    data = json.loads(decrypted_data)
                    with open(env_file, "a") as f:
                        for key, value in data.items():
                             # Handle complex types by converting to string or skipping
                            if isinstance(value, (dict, list)):
                                print(f"Warning: Skipping complex type for key {key}", file=sys.stderr)
                                continue
                            f.write(f"{key}={value}\n")
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON for export: {e}", file=sys.stderr)
            
            elif output_type == "yaml":
                import yaml
                try:
                    data = yaml.safe_load(decrypted_data)
                    with open(env_file, "a") as f:
                        for key, value in data.items():
                            if isinstance(value, (dict, list)):
                                print(f"Warning: Skipping complex type for key {key}", file=sys.stderr)
                                continue
                            f.write(f"{key}={value}\n")
                except yaml.YAMLError as e:
                    print(f"Error parsing YAML for export: {e}", file=sys.stderr)

    except subprocess.CalledProcessError as e:
        print(f"Error decrypting file: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    setup_keys()
    decrypt_file()
