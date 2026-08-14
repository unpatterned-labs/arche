# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for document metadata reading.

`ParsedDocument.metadata` was an empty dict while every real PDF in the repo
carried the fields it was meant to hold. This is data that was being discarded,
not data that was missing, and two things fall out of reading it:

* `author='Condor Flugdienst GmbH'` is an issuer identity with no model behind
  it — the same field the entity extractor was guessing at from body text.
* `Title` on a bank statement carries an account fragment and `Subject` on a
  flight confirmation carries a booking reference, so metadata is personal data
  and must be masked and scanned like any other text.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from arche.doc._metadata import (
    PRODUCER_FAMILIES,
    ContentCredentials,
    DocumentMetadata,
    Producer,
    classify_producer,
    read_metadata,
)

_REPO = Path(__file__).resolve().parents[3]
_BENCH = _REPO / "data" / "doc_bench"


def _has_pdf_backend() -> bool:
    """Either metadata backend. Both arrive with an extra, not the base install."""
    for module in ("pypdfium2", "fitz"):
        try:
            __import__(module)
            return True
        except ImportError:
            continue
    return False


_PDF_BACKEND = _has_pdf_backend()


class TestProducerClassification:
    @pytest.mark.parametrize(("raw", "family", "tool"), [
        ("Skia/PDF m145", "browser-print", "Chromium"),
        ("Chromium", "browser-print", "Chromium"),
        ("WeasyPrint 65.1", "html-renderer", "WeasyPrint"),
        ("iText® 5.5.1 ©2000-2014 iText Group NV", "enterprise-report", "iText"),
        ("PDFlib 8.0.2-i (Linux)", "enterprise-report", "PDFlib"),
        ("Crystal Reports", "enterprise-report", "Crystal Reports"),
        ("Hyperion SQR Production Reporting", "enterprise-report", "Hyperion SQR"),
        ("Microsoft® Word for Microsoft 365", "office", "Microsoft Word"),
        ("Adobe Acrobat Pro DC", "authoring", "Adobe Acrobat"),
        ("ReportLab PDF Library", "library", "ReportLab"),
    ])
    def test_real_producer_strings(self, raw, family, tool):
        got = classify_producer(raw)
        assert (got.family, got.tool) == (family, tool)

    def test_the_family_is_the_useful_part(self):
        """Browser-printed and server-rendered imply different trust.

        A human printing from a browser and an enterprise reporting system
        emitting a statement are very different provenance, and that is
        readable without any cryptographic manifest.
        """
        assert classify_producer("Skia/PDF m145").family == "browser-print"
        assert classify_producer("WeasyPrint 65.1").family == "html-renderer"
        assert classify_producer("Crystal Reports").family == "enterprise-report"

    def test_an_unknown_tool_keeps_its_raw_text(self):
        """A tool we have not seen is not a tool that does not exist."""
        got = classify_producer("Wibble PDF Writer 3.2")
        assert got.family == "unknown"
        assert got.raw == "Wibble PDF Writer 3.2"

    def test_empty_is_falsy(self):
        assert not classify_producer("")
        assert not Producer()

    def test_every_family_is_declared(self):
        for _pattern, family, _tool in __import__(
            "arche.doc._metadata", fromlist=["_PRODUCER_RULES"]
        )._PRODUCER_RULES:
            assert family in PRODUCER_FAMILIES


class TestPdfDates:
    def test_offset_is_parsed_and_kept(self):
        from arche.doc._metadata import _parse_pdf_date

        when, offset = _parse_pdf_date("D:20250327055703+01'00'")
        assert when == datetime.fromisoformat("2025-03-27T05:57:03+01:00")
        assert offset == 60

    def test_negative_and_zulu_offsets(self):
        from arche.doc._metadata import _parse_pdf_date

        assert _parse_pdf_date("D:20250519030028-07'00'")[1] == -420
        assert _parse_pdf_date("D:20260301090456Z")[1] == 0

    @pytest.mark.parametrize("raw", ["", "   ", "not a date", "D:", "D:99"])
    def test_unparseable_is_missing_not_an_error(self, raw):
        from arche.doc._metadata import _parse_pdf_date

        assert _parse_pdf_date(raw) == (None, None)


class TestReadMetadata:
    def test_a_missing_file_returns_empty_and_does_not_raise(self):
        """Failing to read metadata must never fail a parse."""
        got = read_metadata("does-not-exist.pdf")
        assert got.backend == "none"
        assert not got

    def test_an_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="unknown metadata backend"):
            read_metadata("x.pdf", backend="magic")

    @pytest.mark.skipif(not _PDF_BACKEND, reason="no PDF metadata backend installed")
    @pytest.mark.skipif(not (_BENCH / "invoice_12_ak.pdf").exists(),
                        reason="doc_bench corpus not present")
    def test_the_issuer_arrives_for_free(self):
        """No model, no extraction — the PDF header states who issued it."""
        got = read_metadata(_BENCH / "invoice_12_ak.pdf")
        assert got.author == "Condor Flugdienst GmbH"
        assert got.producer.family == "enterprise-report"
        assert got.tz_offset_minutes == 60

    @pytest.mark.skipif(not _PDF_BACKEND, reason="no PDF metadata backend installed")
    @pytest.mark.skipif(not (_BENCH / "invoice_27.pdf").exists(),
                        reason="doc_bench corpus not present")
    def test_a_browser_printed_document_is_recognised(self):
        got = read_metadata(_BENCH / "invoice_27.pdf")
        assert got.producer.family == "browser-print"
        assert got.page_count == 2


class TestMetadataIsPersonalData:
    """The gap this closes: a card number in a PDF Title was invisible."""

    def test_free_text_fields_are_exposed_for_scanning(self):
        got = DocumentMetadata(
            title="Condor Booking Confirmation / Flight no. 11828454",
            author="Condor Flugdienst GmbH",
        )
        values = got.text_values()
        assert "title" in values and "author" in values
        assert "11828454" in values["title"]

    def test_export_masks_by_default(self):
        got = DocumentMetadata(title="Monzo_bank_statement_2025-12-01_2231")
        masked = got.to_dict()["title"]
        assert masked.startswith("Monz")
        assert "2231" not in masked
        assert got.to_dict(reveal=True)["title"] == got.title

    def test_structural_fields_are_never_masked(self):
        """Producer family is not personal data and is useful in a report."""
        got = DocumentMetadata(producer=classify_producer("Skia/PDF m145"))
        assert got.to_dict()["producer_family"] == "browser-print"


class TestContentCredentials:
    """Shipped as a type with an honest empty state, not as a reader."""

    def test_absent_is_the_default(self):
        assert ContentCredentials().status == "absent"

    def test_absence_never_implies_human_authorship(self):
        """The most dangerous possible reading of this field, refused.

        `ai_generated` is tri-state: absence of a manifest yields None
        (unknown), never False.
        """
        creds = ContentCredentials()
        assert creds.ai_generated is None
        assert creds.ai_generated is not False

    def test_the_explanation_says_so_in_words(self):
        text = ContentCredentials().explain()
        assert "not evidence of tampering" in text
        assert "not evidence of human authorship" in text


class TestParsedDocumentIntegration:
    def test_info_is_never_None(self):
        """A source with no readable metadata yields an empty object."""
        from arche.doc.parse import ParsedDocument

        doc = ParsedDocument(source="nowhere.pdf", text="hi")
        assert isinstance(doc.info, DocumentMetadata)
        assert not doc.info

    def test_metadata_stays_the_single_source_of_truth(self):
        """`info` is a derived view, so the two cannot disagree."""
        from arche.doc.parse import ParsedDocument

        info = DocumentMetadata(author="ACME Ltd", backend="test")
        doc = ParsedDocument(source="x.pdf", text="", metadata={"_info": info})
        assert doc.info is info
        assert doc.info.author == "ACME Ltd"
