import json
import os
import sys
from unittest.mock import mock_open, patch

import pytest

# Add the directory containing detect.py to sys.path so we can import it
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../detect-contexts")))

import detect


class TestDetectLanguage:
    def test_detect_go(self, tmp_path):
        (tmp_path / "go.mod").touch()
        assert detect.detect_language(str(tmp_path)) == "go"

    def test_detect_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").touch()
        assert detect.detect_language(str(tmp_path)) == "rust"

    def test_detect_node(self, tmp_path):
        (tmp_path / "package.json").touch()
        assert detect.detect_language(str(tmp_path)) == "node"

    def test_detect_python_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").touch()
        assert detect.detect_language(str(tmp_path)) == "python"

    def test_detect_python_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert detect.detect_language(str(tmp_path)) == "python"

    def test_detect_java_pom(self, tmp_path):
        (tmp_path / "pom.xml").touch()
        assert detect.detect_language(str(tmp_path)) == "java"

    def test_detect_unknown(self, tmp_path):
        (tmp_path / "other.txt").touch()
        assert detect.detect_language(str(tmp_path)) is None

    def test_detect_nonexistent_dir(self):
        assert detect.detect_language("/nonexistent/path") is None


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
    @patch("builtins.open", new_callable=mock_open)
    @patch("detect.os.environ", {})
    def test_main_flow(self, mock_file, mock_yaml_load, mock_listdir, mock_exists, capsys):
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

        # Parse the JSON output
        matrix_str = captured.out.split("matrix=")[1].split("\n")[0]
        matrix = json.loads(matrix_str)

        assert len(matrix) == 2  # Only Go and Rust should be included

        go_entry = next((i for i in matrix if i["name"] == "app-go"), None)
        assert go_entry is not None
        assert go_entry["language"] == "go"

        rust_entry = next((i for i in matrix if i["name"] == "app-rust"), None)
        assert rust_entry is not None
        assert rust_entry["language"] == "rust"

    @patch("detect.os.path.exists", return_value=False)
    @patch("detect.os.environ", {})
    def test_main_no_skaffold_file(self, mock_exists, capsys):
        detect.main()
        captured = capsys.readouterr()
        assert "matrix=[]" in captured.out
        assert "languages=" in captured.out
        assert "Error: skaffold.yaml not found" in captured.err
