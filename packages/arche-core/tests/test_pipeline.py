"""Tests for the main pipeline entry points."""

from arche import ResolutionResult, __version__
from arche.workflow.pipeline import resolve
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
    # Pinned deliberately: bumping the version is a release decision, so it
    # should require touching a test rather than happening as a side effect.
    #
    # Moved 0.3.0a2 -> 0.4.0a1 in 2026-08. `0.3.0a2` was versioned, changelogged
    # and merged but never published, and was superseded before it could be,
    # while `SECURITY.md` told readers to upgrade to it. Both that advisory and
    # the changelog now say so rather than quietly renumbering.
    #
    # 0.4.0a1 -> 0.4.0a2 is a metadata-only release. Comparing a fresh build
    # against the published 0.4.0a1 wheel showed every code and data member
    # byte-identical; only METADATA differed. The bump exists because the
    # package description, keywords and long description are part of what
    # PyPI serves, and those cannot be corrected in place.
    assert __version__ == "0.4.0a2"
