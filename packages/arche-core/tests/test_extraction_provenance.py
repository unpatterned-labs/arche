# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for extraction provenance in document-derived decisions.

arche signs decisions. For a *record* that is enough, because the caller holds
the record. For a decision derived from a *document* it is not: signing a verdict
while the extraction that produced it goes unrecorded means the decision can be
re-run approximately and never re-verified.

A parser upgrade changes the text, which changes the record, which changes the
verdict — and without provenance nothing records that it did. Every cited span
also indexes into one specific rendering, so a citation without a text digest
points at the wrong characters after any re-parse, which is worse than pointing
at nothing.

The standard this holds itself to: **a signed wrong merge with opaque extraction
provenance is worse than an unsigned heuristic**, because it lends institutional
legitimacy to something the reader cannot independently inspect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arche.canonical import Reference
from arche.doc.parse import _extraction_provenance
from arche.resolve import pairwise

_BENCH = Path(__file__).resolve().parents[3] / "data" / "doc_bench"


class TestWhatIsRecorded:
    def test_the_four_facts(self):
        got = _extraction_provenance(__file__, "some rendered text", do_ocr=False)
        assert got["parser"] == "docling"
        assert got["ocr"] is False
        assert got["text_sha256"]
        assert got["artifact_sha256"], "a real file must be hashed"

    def test_the_artifact_hash_is_of_bytes_not_the_name(self, tmp_path):
        """Two files called `invoice.pdf` are not the same document."""
        one = tmp_path / "a" / "invoice.pdf"
        two = tmp_path / "b" / "invoice.pdf"
        for path, body in ((one, b"first"), (two, b"second")):
            path.parent.mkdir(parents=True)
            path.write_bytes(body)
        assert (_extraction_provenance(str(one), "t", None)["artifact_sha256"]
                != _extraction_provenance(str(two), "t", None)["artifact_sha256"])

    def test_the_same_bytes_under_a_different_name_hash_alike(self, tmp_path):
        one, two = tmp_path / "x.pdf", tmp_path / "y.pdf"
        one.write_bytes(b"identical")
        two.write_bytes(b"identical")
        assert (_extraction_provenance(str(one), "t", None)["artifact_sha256"]
                == _extraction_provenance(str(two), "t", None)["artifact_sha256"])

    def test_the_text_digest_anchors_citations(self):
        """A span means nothing without the rendering it indexes into."""
        a = _extraction_provenance(__file__, "rendering one", None)
        b = _extraction_provenance(__file__, "rendering two", None)
        assert a["text_sha256"] != b["text_sha256"]

    def test_ocr_travels_because_it_changes_the_text(self):
        on = _extraction_provenance(__file__, "t", do_ocr=True)
        off = _extraction_provenance(__file__, "t", do_ocr=False)
        assert on["ocr"] is True and off["ocr"] is False

    def test_a_url_or_missing_file_degrades_rather_than_raises(self):
        """Failing to record provenance must never fail a parse.

        The absence is then visible in the pins rather than silently assumed.
        """
        got = _extraction_provenance("https://example.com/a.pdf", "text", None)
        assert "artifact_sha256" not in got
        assert got["parser"] == "docling"


class TestItReachesTheDecision:
    """The point of all of it: provenance must be INSIDE the hash."""

    @staticmethod
    def _decide(extraction):
        a = Reference.from_record({"name": "Amara Nwosu", "email": "a@example.com"})
        b = Reference.from_record({"name": "Amara Nwosu", "email": "a@example.com"})
        return pairwise(a, b, entity="person",
                        extra_pins={"extraction": extraction} if extraction else None)

    def test_a_different_parser_version_changes_the_decision_id(self):
        """The scenario this exists for: upgrade docling, re-run, get the same
        verdict — and be able to tell that it was not the same decision."""
        old = self._decide({"a": {"parser": "docling", "parser_version": "2.110.0"}})
        new = self._decide({"a": {"parser": "docling", "parser_version": "2.111.0"}})
        assert old.decision_id != new.decision_id

    def test_different_input_bytes_change_the_decision_id(self):
        one = self._decide({"a": {"artifact_sha256": "aaaa"}})
        two = self._decide({"a": {"artifact_sha256": "bbbb"}})
        assert one.decision_id != two.decision_id

    def test_a_different_rendering_changes_the_decision_id(self):
        """Because every cited span indexes into that rendering."""
        one = self._decide({"a": {"text_sha256": "1111"}})
        two = self._decide({"a": {"text_sha256": "2222"}})
        assert one.decision_id != two.decision_id

    def test_ocr_changes_the_decision_id(self):
        assert (self._decide({"a": {"ocr": True}}).decision_id
                != self._decide({"a": {"ocr": False}}).decision_id)

    def test_identical_provenance_reproduces_the_same_decision_id(self):
        """Reproducibility must survive: same inputs, same id, no timestamp."""
        prov = {"a": {"parser": "docling", "parser_version": "2.110.0",
                      "artifact_sha256": "abc", "text_sha256": "def"}}
        assert self._decide(prov).decision_id == self._decide(prov).decision_id

    def test_recording_provenance_changes_the_id_at_all(self):
        """Pinning a backend name is provenance labelling, not auditability —
        so the absence of provenance must itself be distinguishable."""
        assert (self._decide(None).decision_id
                != self._decide({"a": {"parser": "docling"}}).decision_id)


@pytest.mark.skipif(not (_BENCH / "invoice_27.pdf").exists(),
                    reason="doc_bench corpus not present")
class TestEndToEnd:
    def test_parse_records_provenance(self):
        from arche.doc import DOC_FEATURE_AVAILABLE, parse

        if not DOC_FEATURE_AVAILABLE:
            pytest.skip("parse() requires the [doc] extra (docling)")
        got = parse(_BENCH / "invoice_27.pdf").provenance
        assert got["artifact_sha256"] and got["text_sha256"]
        assert got["parser_version"], "an unversioned parser cannot be cited"

    def test_the_report_carries_it_per_document(self):
        from arche.doc import DOC_FEATURE_AVAILABLE

        if not DOC_FEATURE_AVAILABLE:
            pytest.skip("parse() requires the [doc] extra (docling)")
        from arche import resolve_documents

        report = resolve_documents(str(_BENCH / "invoice_27.pdf"), progress=False)
        assert report.provenance
        for entry in report.provenance.values():
            assert "artifact_sha256" in entry and "text_sha256" in entry
