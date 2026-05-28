"""Tests for the main pipeline entry points."""

from arche import ResolutionResult, __version__, resolve
from arche.workflow.pipeline import ArchePipeline


def test_resolve_returns_result(sample_identity_text):
    result = resolve(sample_identity_text, backend="regex")
    assert isinstance(result, ResolutionResult)
    assert result.entity_count >= 0
    assert result.pii_count >= 0


def test_resolve_to_dict(sample_identity_text):
    result = resolve(sample_identity_text, backend="regex")
    d = result.to_dict()
    assert "entities" in d
    assert "resolved" in d
    assert "pii" in d
    assert "signals" in d
    assert "summary" in d


def test_resolve_to_json(sample_identity_text):
    result = resolve(sample_identity_text, backend="regex")
    j = result.to_json()
    import json
    parsed = json.loads(j)
    assert "entities" in parsed


def test_pipeline_class():
    pipeline = ArchePipeline(backend="regex")
    result = pipeline.run("Fatima Abdullahi, NIN 12345678901")
    assert isinstance(result, ResolutionResult)


def test_pipeline_batch():
    pipeline = ArchePipeline(backend="regex")
    results = pipeline.run_batch(["text one", "text two"])
    assert len(results) == 2


def test_version():
    assert __version__ == "0.2.0a3"
