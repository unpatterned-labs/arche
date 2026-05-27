# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.doc — docling integration (optional ``[doc]`` extra)."""

from __future__ import annotations

import pytest

from arche.doc import DOC_FEATURE_AVAILABLE, DoclingNotInstalledError, parse


# ── Optionality contract ────────────────────────────────────────────────────


def test_doc_feature_flag_reflects_install_state():
    """DOC_FEATURE_AVAILABLE is the canonical optional-install sentinel."""
    import importlib.util
    expected = importlib.util.find_spec("docling") is not None
    assert DOC_FEATURE_AVAILABLE is expected


@pytest.mark.skipif(
    DOC_FEATURE_AVAILABLE,
    reason="docling is installed; this test verifies the missing-dep error path",
)
def test_parse_raises_helpful_error_when_docling_missing():
    with pytest.raises(DoclingNotInstalledError) as exc_info:
        parse("nonexistent.pdf")
    assert "arche-core[doc]" in str(exc_info.value)
    assert "doc-ocr" in str(exc_info.value)


# ── Smoke test when docling IS installed ────────────────────────────────────


@pytest.mark.skipif(
    not DOC_FEATURE_AVAILABLE,
    reason="Requires arche-core[doc] extra (docling)",
)
def test_parse_imports_docling_lazily():
    """Importing arche.doc must not eagerly load docling's heavy modules."""
    import sys

    # The shallow `import docling` probe ran at import time but the
    # converter never loaded.
    assert "docling.document_converter" not in sys.modules


@pytest.mark.skipif(
    not DOC_FEATURE_AVAILABLE,
    reason="Requires arche-core[doc] extra (docling)",
)
def test_pipeline_process_file_round_trip(tmp_path):
    """End-to-end: write a markdown file, parse via docling, run policy."""
    from arche import Pipeline

    sample = tmp_path / "sample.md"
    sample.write_text(
        "# Customer record\n\n"
        "NIN: 12345678901\n"
        "BVN: 22156789012\n"
        "Phone: +234 803 555 7890\n",
        encoding="utf-8",
    )

    pipeline = Pipeline(jurisdiction="NG")
    result = pipeline.process_file(sample)

    # Pipeline.Result fields populate as usual
    assert isinstance(result.detections, list)
    assert result.metadata["source_file"] == str(sample)
    # NIN + BVN should be detected from the parsed text
    categories = {d.category for d in result.detections}
    assert "PII-2-NIN" in categories or "PII-2-BVN" in categories
