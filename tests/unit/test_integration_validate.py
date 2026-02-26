"""
Unit tests for integration-validate action contract.

The action resolves the primary build context from pipeline-context (first non-helm
matrix item, or at validate-context-index). These tests exercise the same jq logic
so all possibilities (Rust, Go, index selection, empty matrix) are covered.
"""

import json


def resolve_validate_context(pipeline_context: dict, index: int = 0) -> dict | None:
    """
    Resolve validate context the same way the action's Resolve step does (jq contract).
    Returns the context object or None if no build context at that index.
    """
    matrix = pipeline_context.get("matrix") or []
    non_helm = [m for m in matrix if m.get("language") != "helm"]
    if index < 0 or index >= len(non_helm):
        return None
    ctx = non_helm[index]
    return {
        "context": json.dumps(ctx),
        "language": ctx.get("language", ""),
        "version": ctx.get("version") or "",
        "ctx_context": ctx.get("context", "."),
    }


class TestResolveValidateContext:
    def test_first_non_helm_rust(self):
        pipeline_context = {
            "matrix": [
                {"name": "app", "context": ".", "language": "rust", "version": "1.75.0"},
                {"name": "helm-chart", "context": "chart", "language": "helm", "version": ""},
            ],
        }
        out = resolve_validate_context(pipeline_context, 0)
        assert out is not None
        assert out["language"] == "rust"
        assert out["version"] == "1.75.0"
        assert out["ctx_context"] == "."

    def test_first_non_helm_go(self):
        pipeline_context = {
            "matrix": [
                {"name": "go-svc", "context": "cmd/server", "language": "go", "version": "1.22"},
            ],
        }
        out = resolve_validate_context(pipeline_context, 0)
        assert out is not None
        assert out["language"] == "go"
        assert out["ctx_context"] == "cmd/server"

    def test_skips_helm_takes_second(self):
        pipeline_context = {
            "matrix": [
                {"name": "helm-a", "context": "chart", "language": "helm", "version": ""},
                {"name": "app-go", "context": ".", "language": "go", "version": "1.21"},
            ],
        }
        out = resolve_validate_context(pipeline_context, 0)
        assert out is not None
        assert out["language"] == "go"

    def test_validate_context_index_one(self):
        pipeline_context = {
            "matrix": [
                {"name": "app-go", "context": "go-svc", "language": "go", "version": "1.21"},
                {"name": "app-rust", "context": "rust-svc", "language": "rust", "version": "stable"},
            ],
        }
        out = resolve_validate_context(pipeline_context, 0)
        assert out["language"] == "go"
        out1 = resolve_validate_context(pipeline_context, 1)
        assert out1["language"] == "rust"
        assert out1["ctx_context"] == "rust-svc"

    def test_empty_matrix_returns_none(self):
        pipeline_context = {"matrix": []}
        assert resolve_validate_context(pipeline_context, 0) is None

    def test_only_helm_returns_none(self):
        pipeline_context = {
            "matrix": [
                {"name": "helm-chart", "context": "chart", "language": "helm", "version": ""},
            ],
        }
        assert resolve_validate_context(pipeline_context, 0) is None

    def test_index_out_of_range_returns_none(self):
        pipeline_context = {
            "matrix": [{"name": "app", "context": ".", "language": "go", "version": "1.21"}],
        }
        assert resolve_validate_context(pipeline_context, 1) is None
        assert resolve_validate_context(pipeline_context, -1) is None

    def test_missing_matrix_treated_as_empty(self):
        assert resolve_validate_context({}, 0) is None
        assert resolve_validate_context({"matrix": None}, 0) is None
