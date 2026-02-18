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

    @patch("detect.os.path.exists")
    @patch("detect.os.listdir")
    @patch("detect.yaml.safe_load")
    @patch("detect.get_file_content")
    @patch("detect.os.environ", {})
    def test_main_multiple_contexts_same_type(
        self, mock_get_content, mock_yaml_load, mock_listdir, mock_exists, capsys
    ):
        # Setup mocks for 2 Go services, 2 Python services, 1 Node service
        mock_exists.side_effect = lambda p: (
            p
            in [
                "skaffold.yaml",
                "./go-svc-1",
                "./go-svc-2",
                "./py-svc-1",
                "./py-svc-2",
                "./node-svc",
            ]
        )

        def listdir_side_effect(path):
            if path in ["./go-svc-1", "./go-svc-2"]:
                return ["go.mod", "main.go"]
            if path in ["./py-svc-1", "./py-svc-2"]:
                return ["requirements.txt", "main.py"]
            if path == "./node-svc":
                return ["package.json"]
            return []

        mock_listdir.side_effect = listdir_side_effect

        def get_content_side_effect(context, filename):
            if context == "./go-svc-1" and filename == "go.mod":
                return "module foo\ngo 1.21\n"
            if context == "./go-svc-2" and filename == "go.mod":
                return "module bar\ngo 1.22\n"
            if context == "./py-svc-1" and filename == ".python-version":
                return "3.11\n"
            if context == "./py-svc-2" and filename == ".python-version":
                return "3.12\n"
            if context == "./node-svc" and filename == "package.json":
                return '{"engines": {"node": "18"}}'
            return None

        mock_get_content.side_effect = get_content_side_effect

        # Mock yaml config
        mock_yaml_load.return_value = {
            "apiVersion": "skaffold/v4beta1",
            "kind": "Config",
            "build": {
                "artifacts": [
                    {"image": "app-go-1", "context": "./go-svc-1"},
                    {"image": "app-go-2", "context": "./go-svc-2"},
                    {"image": "app-py-1", "context": "./py-svc-1"},
                    {"image": "app-py-2", "context": "./py-svc-2"},
                    {"image": "app-node", "context": "./node-svc"},
                ]
            },
        }

        # Run main
        detect.main()

        # Capture output
        captured = capsys.readouterr()

        # Check standard output
        assert "matrix=" in captured.out
        assert "languages=" in captured.out
        assert "pipeline-context=" in captured.out

        # Parse the JSON output from pipeline-context
        context_str = captured.out.split("pipeline-context=")[1].split("\n")[0]
        context = json.loads(context_str)

        # Verify Matrix
        matrix = context["matrix"]
        assert len(matrix) == 5

        # Verify Go entries
        go_1 = next((i for i in matrix if i["name"] == "app-go-1"), None)
        assert go_1 is not None
        assert go_1["version"] == "1.21"
        go_2 = next((i for i in matrix if i["name"] == "app-go-2"), None)
        assert go_2 is not None
        assert go_2["version"] == "1.22"

        # Verify consolidated languages
        languages = context["languages"]
        assert languages == ["go", "node", "python"]

        # Verify aggregated versions (should pick the highest/latest lexicographically)
        versions = context["versions"]
        assert versions["go"] == "1.22"
        # Python versions 3.11 and 3.12 -> 3.12 is lexicographically larger
        # Note: detect_python_version checks .python-version if requirements.txt exists but
        # get_file_content mock needs to handle it.
        # listdir returns requirements.txt, so language=python.
        # detect_python_version checks pyproject.toml then .python-version.
        # Mock get_content returns "3.11" for .python-version for svc-1.
        # For svc-2, it returns "3.12".
        # wait, my get_content mock only handles .python-version if file name is passed.
        # detect.py calls get_file_content(context, ".python-version").
        # My mock handles it. Correct.
        assert versions["python"] == "3.12"
        assert versions["node"] == "18"
