import json
import os
import sys
from unittest.mock import patch

import pytest

# Add the directory containing detect.py to sys.path so we can import it
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../detect-contexts")))

import detect


class TestDetectLanguage:
    def test_detect_go(self, tmp_path):
        f = tmp_path / "go.mod"
        f.write_text("module example\n\ngo 1.21.5\n")
        info = detect.detect_project_info(str(tmp_path))
        assert info["language"] == "go"
        assert info["version"] == "1.21.5"

    def test_detect_rust(self, tmp_path):
        f = tmp_path / "Cargo.toml"
        f.touch()
        # rust-toolchain
        t = tmp_path / "rust-toolchain"
        t.write_text("1.75.0")
        info = detect.detect_project_info(str(tmp_path))
        assert info["language"] == "rust"
        assert info["version"] == "1.75.0"

    def test_detect_node(self, tmp_path):
        f = tmp_path / "package.json"
        f.write_text('{"engines": {"node": ">=18.0.0"}}')
        info = detect.detect_project_info(str(tmp_path))
        assert info["language"] == "node"
        assert info["version"] == ">=18.0.0"

    def test_detect_python_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").touch()
        v = tmp_path / ".python-version"
        v.write_text("3.11.4")
        info = detect.detect_project_info(str(tmp_path))
        assert info["language"] == "python"
        assert info["version"] == "3.11.4"

    def test_detect_java_pom(self, tmp_path):
        f = tmp_path / "pom.xml"
        f.write_text("<project><properties><java.version>17</java.version></properties></project>")
        info = detect.detect_project_info(str(tmp_path))
        assert info["language"] == "java"
        assert info["version"] == "17"

    def test_detect_unknown(self, tmp_path):
        (tmp_path / "other.txt").touch()
        assert detect.detect_project_info(str(tmp_path)) is None

    def test_detect_nonexistent_dir(self):
        assert detect.detect_project_info("/nonexistent/path") is None


class TestMain:
    @pytest.fixture
    def mock_skaffold_yaml(self):
        return """
apiVersion: skaffold/v2beta29
kind: Config
build:
  artifacts:
    - image: app-go
      context: ./go-service
    - image: app-rust
      context: ./rust-service
    - image: app-unknown
      context: ./unknown-service
"""

    @patch("detect.os.path.exists")
    @patch("detect.os.listdir")
    @patch("detect.yaml.safe_load")
    @patch("detect.get_file_content")
    @patch("detect.os.environ", {})
    def test_main_flow(self, mock_get_content, mock_yaml_load, mock_listdir, mock_exists, capsys):
        # Setup mocks
        mock_exists.side_effect = lambda p: (
            p
            in [
                "skaffold.yaml",
                "./go-service",
                "./rust-service",
                "./unknown-service",
            ]
        )

        def listdir_side_effect(path):
            if path == "./go-service":
                return ["go.mod", "main.go"]
            if path == "./rust-service":
                return ["Cargo.toml", "src"]
            if path == "./unknown-service":
                return ["readme.md"]
            return []

        mock_listdir.side_effect = listdir_side_effect

        def get_content_side_effect(context, filename):
            if context == "./go-service" and filename == "go.mod":
                return "module foo\ngo 1.22\n"
            if context == "./rust-service" and filename == "rust-toolchain":
                return "stable"
            return None

        mock_get_content.side_effect = get_content_side_effect

        # Mock yaml config directly
        mock_yaml_load.return_value = {
            "apiVersion": "skaffold/v2beta29",
            "kind": "Config",
            "build": {
                "artifacts": [
                    {"image": "app-go", "context": "./go-service"},
                    {"image": "app-rust", "context": "./rust-service"},
                    {"image": "app-unknown", "context": "./unknown-service"},
                ]
            },
        }

        # Run main
        detect.main()

        # Capture output
        captured = capsys.readouterr()

        # Check standard output (since GITHUB_OUTPUT is not set)
        assert "matrix=" in captured.out
        assert "languages=" in captured.out
        assert "go-version=1.22" in captured.out
        assert "rust-version=stable" in captured.out

        # Parse the JSON output
        matrix_str = captured.out.split("matrix=")[1].split("\n")[0]
        matrix = json.loads(matrix_str)

        assert len(matrix) == 2  # Only Go and Rust should be included

        go_entry = next((i for i in matrix if i["name"] == "app-go"), None)
        assert go_entry is not None
        assert go_entry["language"] == "go"
        assert go_entry["version"] == "1.22"

        rust_entry = next((i for i in matrix if i["name"] == "app-rust"), None)
        assert rust_entry is not None
        assert rust_entry["language"] == "rust"
        # version might be empty if not found in mocked listdir but we mocked get_content...
        # Wait, detect_rust_version iterates filenames. It calls get_file_content("rust-toolchain").
        # But listdir only returns ["Cargo.toml", "src"].
        # existing detect_project_info calls os.listdir first to determine language.
        # "Cargo.toml" is in listdir, so language=rust.
        # Then it calls detect_rust_version, which calls get_file_content.
        # So mocks should work.
        assert rust_entry["version"] == "stable"

    @patch("detect.os.path.exists", return_value=False)
    @patch("detect.os.environ", {})
    def test_main_no_skaffold_file(self, mock_exists, capsys):
        detect.main()
        captured = capsys.readouterr()
        assert "matrix=[]" in captured.out
        assert "languages=" in captured.out
        assert "Error: skaffold.yaml not found" in captured.err
