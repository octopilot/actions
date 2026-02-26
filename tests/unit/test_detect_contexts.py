import json
import os
import sys
from unittest.mock import patch

import pytest

# Add the directory containing detect.py to sys.path so we can import it
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../detect-contexts")))

import detect


class TestGetFileContent:
    def test_returns_content_when_file_exists(self, tmp_path):
        (tmp_path / "foo.txt").write_text("hello")
        assert detect.get_file_content(str(tmp_path), "foo.txt") == "hello"

    def test_returns_none_when_file_missing(self, tmp_path):
        assert detect.get_file_content(str(tmp_path), "missing.txt") is None

    def test_returns_none_when_dir_missing(self):
        assert detect.get_file_content("/nonexistent/dir", "x") is None


class TestVersionDetectors:
    def test_detect_go_version(self, tmp_path):
        (tmp_path / "go.mod").write_text("module x\n\ngo 1.22.0\n")
        assert detect.detect_go_version(str(tmp_path)) == "1.22.0"

    def test_detect_go_version_missing(self, tmp_path):
        assert detect.detect_go_version(str(tmp_path)) == ""

    def test_detect_rust_version_plain_file(self, tmp_path):
        (tmp_path / "rust-toolchain").write_text("1.75.0")
        assert detect.detect_rust_version(str(tmp_path)) == "1.75.0"

    def test_detect_rust_version_toml(self, tmp_path):
        (tmp_path / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "stable"')
        assert detect.detect_rust_version(str(tmp_path)) == "stable"

    def test_detect_rust_version_missing(self, tmp_path):
        assert detect.detect_rust_version(str(tmp_path)) == ""

    def test_detect_node_version_engines(self, tmp_path):
        (tmp_path / "package.json").write_text('{"engines": {"node": ">=18"}}')
        assert detect.detect_node_version(str(tmp_path)) == ">=18"

    def test_detect_node_version_nvmrc(self, tmp_path):
        (tmp_path / ".nvmrc").write_text("20.10.0")
        assert detect.detect_node_version(str(tmp_path)) == "20.10.0"

    def test_detect_node_version_missing(self, tmp_path):
        assert detect.detect_node_version(str(tmp_path)) == ""

    def test_detect_python_version_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.11"')
        assert detect.detect_python_version(str(tmp_path)) == ">=3.11"

    def test_detect_python_version_file(self, tmp_path):
        (tmp_path / ".python-version").write_text("3.12.1")
        assert detect.detect_python_version(str(tmp_path)) == "3.12.1"

    def test_detect_python_version_missing(self, tmp_path):
        assert detect.detect_python_version(str(tmp_path)) == ""

    def test_detect_java_version_pom_java_version(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project><properties><java.version>17</java.version></properties></project>")
        assert detect.detect_java_version(str(tmp_path)) == "17"

    def test_detect_java_version_pom_compiler_source(self, tmp_path):
        (tmp_path / "pom.xml").write_text(
            "<project><properties><maven.compiler.source>11</maven.compiler.source></properties></project>"
        )
        assert detect.detect_java_version(str(tmp_path)) == "11"

    def test_detect_java_version_gradle_groovy(self, tmp_path):
        (tmp_path / "build.gradle").write_text("sourceCompatibility = JavaVersion.VERSION_17")
        assert detect.detect_java_version(str(tmp_path)) == "17"

    def test_detect_java_version_gradle_kts_language_version(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text(
            "java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }"
        )
        assert detect.detect_java_version(str(tmp_path)) == "17"

    def test_detect_java_version_gradle_kts_jvm_target(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text("jvmTarget.set(JvmTarget.JVM_21)")
        assert detect.detect_java_version(str(tmp_path)) == "21"

    def test_detect_java_version_missing(self, tmp_path):
        assert detect.detect_java_version(str(tmp_path)) == ""


class TestJavaVersionToBpJvm:
    def test_major_only(self):
        assert detect._java_version_to_bp_jvm("17") == "17"

    def test_legacy_format(self):
        assert detect._java_version_to_bp_jvm("1.8") == "8"

    def test_empty(self):
        assert detect._java_version_to_bp_jvm("") == ""

    def test_stripped(self):
        assert detect._java_version_to_bp_jvm("  17  ") == "17"


class TestGradleBpEnvFromContext:
    def test_non_java_returns_empty(self, tmp_path):
        (tmp_path / "readme.txt").touch()
        assert detect._gradle_bp_env_from_context(str(tmp_path)) == {}

    def test_java_gradle_kts_sets_bp_jvm_and_build_file(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text(
            "java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }"
        )
        result = detect._gradle_bp_env_from_context(str(tmp_path))
        assert result["BP_JVM_VERSION"] == "17"
        assert result["BP_GRADLE_BUILD_FILE"] == "build.gradle.kts"

    def test_java_gradle_groovy_sets_build_file(self, tmp_path):
        (tmp_path / "build.gradle").write_text("sourceCompatibility = '11'")
        result = detect._gradle_bp_env_from_context(str(tmp_path))
        assert result["BP_JVM_VERSION"] == "11"
        assert result["BP_GRADLE_BUILD_FILE"] == "build.gradle"

    def test_java_no_version_still_sets_build_file(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text("// no version")
        result = detect._gradle_bp_env_from_context(str(tmp_path))
        assert result["BP_GRADLE_BUILD_FILE"] == "build.gradle.kts"
        assert "BP_JVM_VERSION" not in result


class TestDetectHelmCharts:
    def test_finds_chart_dirs(self, tmp_path):
        (tmp_path / "chart").mkdir()
        (tmp_path / "chart" / "Chart.yaml").write_text("name: foo")
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "Chart.yaml").write_text("name: bar")
        result = detect.detect_helm_charts(str(tmp_path))
        assert set(result) == {"chart", "other"}

    def test_skips_git(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "Chart.yaml").write_text("x")
        result = detect.detect_helm_charts(str(tmp_path))
        assert ".git" not in result

    def test_root_chart_as_dot(self, tmp_path):
        (tmp_path / "Chart.yaml").write_text("name: root")
        result = detect.detect_helm_charts(str(tmp_path))
        assert "." in result


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


class TestBuildPipelineContext:
    """Test build_pipeline_context in isolation (no file I/O for skaffold, no env)."""

    def test_build_pipeline_context_returns_full_structure(self, tmp_path):
        (tmp_path / "go-svc").mkdir()
        (tmp_path / "go-svc" / "go.mod").write_text("module x\n\ngo 1.21\n")
        (tmp_path / "chart").mkdir()
        (tmp_path / "chart" / "Chart.yaml").write_text("name: c\n")
        config = {
            "build": {
                "artifacts": [
                    {"image": "app-go", "context": "go-svc"},
                ]
            },
        }
        ctx = detect.build_pipeline_context(config, str(tmp_path))
        assert "matrix" in ctx
        assert "languages" in ctx
        assert "versions" in ctx
        assert "chart_paths" in ctx
        assert "integration_matrix" in ctx
        assert "go" in ctx["languages"]
        assert "helm" in ctx["languages"]
        assert ctx["versions"]["go"] == "1.21"
        assert len(ctx["integration_matrix"]) >= 1
        go_entries = [e for e in ctx["integration_matrix"] if e.get("type") == "image" and e.get("suffix") == "go"]
        assert len(go_entries) == 1
        assert go_entries[0]["build_method"] == "pack"

    def test_build_matrix_include_uses_repo_root(self, tmp_path):
        (tmp_path / "rust-svc").mkdir()
        (tmp_path / "rust-svc" / "Cargo.toml").write_text('[package]\nname="x"\n')
        (tmp_path / "rust-svc" / "rust-toolchain").write_text("1.75")
        artifacts = [{"image": "app-rust", "context": "rust-svc"}]
        matrix = detect.build_matrix_include(artifacts, str(tmp_path))
        assert len(matrix) == 1
        assert matrix[0]["language"] == "rust"
        assert matrix[0]["version"] == "1.75"


class TestMainEarlyExit:
    def test_missing_skaffold_outputs_empty_pipeline_context(self, tmp_path, capsys):
        with patch.dict(os.environ, {"SKAFFOLD_FILE": str(tmp_path / "nonexistent.yaml")}, clear=False):
            detect.main()
        captured = capsys.readouterr()
        assert "pipeline-context=" in captured.out
        ctx_str = captured.out.split("pipeline-context=")[1].split("\n")[0]
        ctx = json.loads(ctx_str)
        assert ctx["matrix"] == []
        assert ctx["integration_matrix"] == []
        assert ctx["chart_paths"] == []


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

    @patch("detect.os.walk")
    def test_main_flow(self, mock_walk, tmp_path, capsys):
        mock_walk.return_value = iter([])  # no helm charts
        (tmp_path / "skaffold.yaml").write_text("""apiVersion: skaffold/v2beta29
kind: Config
build:
  artifacts:
    - image: app-go
      context: go-service
    - image: app-rust
      context: rust-service
    - image: app-unknown
      context: unknown-service
""")
        (tmp_path / "go-service").mkdir()
        (tmp_path / "go-service" / "go.mod").write_text("module foo\n\ngo 1.22\n")
        (tmp_path / "rust-service").mkdir()
        (tmp_path / "rust-service" / "Cargo.toml").write_text('[package]\nname = "x"\n')
        (tmp_path / "rust-service" / "rust-toolchain").write_text("stable")
        (tmp_path / "unknown-service").mkdir()
        (tmp_path / "unknown-service" / "readme.md").write_text("")

        with patch.dict(os.environ, {"SKAFFOLD_FILE": str(tmp_path / "skaffold.yaml")}, clear=False):
            detect.main()

        captured = capsys.readouterr()
        assert "matrix=" in captured.out
        assert "languages=" in captured.out
        assert "go-version=1.22" in captured.out
        assert "rust-version=stable" in captured.out

        matrix_str = captured.out.split("matrix=")[1].split("\n")[0]
        matrix = json.loads(matrix_str)
        assert len(matrix) == 2  # Only Go and Rust (unknown has no language detected)

        go_entry = next((i for i in matrix if i["name"] == "app-go"), None)
        assert go_entry is not None
        assert go_entry["language"] == "go"
        assert go_entry["version"] == "1.22"

        rust_entry = next((i for i in matrix if i["name"] == "app-rust"), None)
        assert rust_entry is not None
        assert rust_entry["language"] == "rust"
        assert rust_entry["version"] == "stable"

    @patch("detect.os.walk")
    def test_main_multiple_contexts_same_type(self, mock_walk, tmp_path, capsys):
        mock_walk.return_value = iter([])  # no helm charts
        (tmp_path / "skaffold.yaml").write_text("""apiVersion: skaffold/v4beta1
kind: Config
build:
  artifacts:
    - image: app-go-1
      context: go-svc-1
    - image: app-go-2
      context: go-svc-2
    - image: app-py-1
      context: py-svc-1
    - image: app-py-2
      context: py-svc-2
    - image: app-node
      context: node-svc
""")
        for d in ["go-svc-1", "go-svc-2", "py-svc-1", "py-svc-2", "node-svc"]:
            (tmp_path / d).mkdir()
        (tmp_path / "go-svc-1" / "go.mod").write_text("module foo\n\ngo 1.21\n")
        (tmp_path / "go-svc-2" / "go.mod").write_text("module bar\n\ngo 1.22\n")
        (tmp_path / "py-svc-1" / "requirements.txt").write_text("")
        (tmp_path / "py-svc-1" / ".python-version").write_text("3.11")
        (tmp_path / "py-svc-2" / "requirements.txt").write_text("")
        (tmp_path / "py-svc-2" / ".python-version").write_text("3.12")
        (tmp_path / "node-svc" / "package.json").write_text('{"engines": {"node": "18"}}')

        with patch.dict(os.environ, {"SKAFFOLD_FILE": str(tmp_path / "skaffold.yaml")}, clear=False):
            detect.main()

        captured = capsys.readouterr()
        assert "matrix=" in captured.out
        assert "pipeline-context=" in captured.out

        context_str = captured.out.split("pipeline-context=")[1].split("\n")[0]
        context = json.loads(context_str)
        matrix = context["matrix"]
        assert len(matrix) == 5

        go_1 = next((i for i in matrix if i["name"] == "app-go-1"), None)
        assert go_1 is not None and go_1["version"] == "1.21"
        go_2 = next((i for i in matrix if i["name"] == "app-go-2"), None)
        assert go_2 is not None and go_2["version"] == "1.22"

        assert context["languages"] == ["go", "node", "python"]
        assert context["versions"]["go"] == "1.22"
        assert context["versions"]["python"] == "3.12"
        assert context["versions"]["node"] == "18"

    def test_main_integration_matrix_and_pipeline_context(self, tmp_path, capsys):
        # Real files: one artifact with Dockerfile -> docker, one with build.gradle.kts -> pack, one chart.
        (tmp_path / "skaffold.yaml").write_text("""apiVersion: skaffold/v4beta7
kind: Config
build:
  artifacts:
    - image: ghcr.io/org/app-monitor
      context: go-svc
    - image: ghcr.io/org/app-cronjob
      context: pack-svc
      buildpacks:
        builder: paketobuildpacks/builder-jammy-base
""")
        (tmp_path / "go-svc").mkdir()
        (tmp_path / "go-svc" / "Dockerfile").write_text("FROM scratch")
        (tmp_path / "go-svc" / "go.mod").write_text("module x\n\ngo 1.21\n")
        (tmp_path / "pack-svc").mkdir()
        (tmp_path / "pack-svc" / "build.gradle.kts").write_text(
            "java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }"
        )
        (tmp_path / "chart").mkdir()
        (tmp_path / "chart" / "Chart.yaml").write_text("name: mychart\nversion: 0.1.0\n")

        with patch.dict(os.environ, {"SKAFFOLD_FILE": str(tmp_path / "skaffold.yaml")}, clear=False):
            detect.main()

        captured = capsys.readouterr()
        assert "pipeline-context=" in captured.out
        ctx_str = captured.out.split("pipeline-context=")[1].split("\n")[0]
        ctx = json.loads(ctx_str)
        assert "integration_matrix" in ctx
        im = ctx["integration_matrix"]
        image_entries = [e for e in im if e.get("type") == "image"]
        chart_entries = [e for e in im if e.get("type") == "chart"]
        assert len(image_entries) == 2
        assert len(chart_entries) == 1
        monitor = next((e for e in image_entries if e.get("suffix") == "monitor"), None)
        cronjob = next((e for e in image_entries if e.get("suffix") == "cronjob"), None)
        assert monitor is not None
        assert cronjob is not None
        assert monitor["build_method"] == "docker"
        assert monitor["output_key"] == "image_monitor"
        assert monitor.get("dockerfile") == "Dockerfile"
        assert cronjob["build_method"] == "pack"
        assert cronjob["output_key"] == "image_cronjob"
        assert "builder" in cronjob
        assert "BP_JVM_VERSION" in (cronjob.get("build_env") or "")
        assert "BP_GRADLE_BUILD_FILE" in (cronjob.get("build_env") or "")
        assert chart_entries[0]["output_key"] == "chart"
        assert chart_entries[0]["path"] == "chart"

    def test_integration_matrix_chart_context_skips_duplicate_chart_entry(self, tmp_path, capsys):
        # When a skaffold artifact has context "chart" (pack + helm buildpack), chart_paths also
        # contains "chart". We must not add a second type=chart entry — one job (pack) is enough.
        (tmp_path / "skaffold.yaml").write_text("""apiVersion: skaffold/v4beta7
kind: Config
build:
  artifacts:
    - image: ghcr.io/org/cronjob-log-monitor
      context: .
    - image: ghcr.io/org/cronjob-log-monitor-chart
      context: chart
      buildpacks:
        builder: ghcr.io/octopilot/builder-jammy-base:test
""")
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"\nversion = "0.1.0"\n')
        (tmp_path / "chart").mkdir()
        (tmp_path / "chart" / "Chart.yaml").write_text("name: cronjob-log-monitor\nversion: 0.1.0\n")

        with patch.dict(os.environ, {"SKAFFOLD_FILE": str(tmp_path / "skaffold.yaml")}, clear=False):
            detect.main()

        captured = capsys.readouterr()
        assert "pipeline-context=" in captured.out
        ctx_str = captured.out.split("pipeline-context=")[1].split("\n")[0]
        ctx = json.loads(ctx_str)
        im = ctx["integration_matrix"]
        image_entries = [e for e in im if e.get("type") == "image"]
        chart_entries = [e for e in im if e.get("type") == "chart"]
        # Two image artifacts (app + chart), no separate chart entry (chart context already built as image)
        assert len(image_entries) == 2
        assert len(chart_entries) == 0
        chart_image = next((e for e in image_entries if e.get("suffix") == "chart"), None)
        assert chart_image is not None
        assert chart_image["context"] == "chart"
        assert chart_image["output_key"] == "image_chart"
        assert chart_image["build_method"] == "pack"
