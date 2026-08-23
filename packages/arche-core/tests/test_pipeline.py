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
    # 0.4.0a3 was prepared and never published. It was scoped as a
    # documentation release, then a matching change landed in the same tree,
    # which would have made its changelog false. Skipped rather than rewritten,
    # so the version number and the claim stay in step. Nothing referenced it:
    # it was never on the index and never tagged.
    #
    # 0.4.0a4 shipped and is on the index. What landed after it was prepared as
    # 0.4.0a5 and released as 0.5.0a1: a Splink scoring backend, a date
    # comparator in the `person` pack, two pin fixes, and `report.review_pack`.
    # 0.4.0a5 was never published, so renaming it left nothing pointing at it.
    #
    # The minor version moved because a replaceable scorer changes what the
    # library is, not merely what it scores. An alpha suffix says the surface
    # may still move; it should not be asked to also hide a change of shape.
    #
    # 0.6.0a1 moves the minor again, on the same rule. It adds public API that
    # did not exist — `arche.coverage`, `arche.policy.statute_for`,
    # `arche.resolve.compare_names`, `arche.review.read_records`,
    # `Pipeline.effective_detectors` — and a fifth refusal in the egress guard,
    # which is a behaviour change rather than an addition. A patch bump would
    # have described that as a fix.
    #
    # It is also the release `arche-mcp` pins against. Every one of those five
    # names is imported by the MCP server, so publishing 0.5.0a1 and pointing
    # arche-mcp at it would ship a package that fails on import.
    assert __version__ == "0.6.0a1"
