# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for tabular export.

`to_rows()` is the primitive and the seam: pandas, Excel, BigQuery and Google
Sheets are each three lines of user code on top of it, with no dependency and no
authentication story for this library to own.
"""

from __future__ import annotations

import csv
import io

import pytest

from arche.doc._documents import DocumentReport
from arche.doc._progress import Timing


@pytest.fixture
def report() -> DocumentReport:
    r = DocumentReport(entity="person")
    r.records = {
        "a.pdf": {"name": "Amara Nwosu", "email": "amara@example.com"},
        "b.pdf": {"name": "Amara Nwosu", "phone": "08035557890"},
    }
    r.detections = {"a.pdf": {"PII-3-EMAIL": 1}, "b.pdf": {"PII-3-PHONE": 2}}
    r.jurisdictions = {"a.pdf": {"country": "NG", "confidence": 0.9},
                       "b.pdf": {"country": None, "confidence": 0.2}}
    r.metadata = {"a.pdf": {"producer_family": "browser-print"}}
    r.timing = Timing(per_document={"a.pdf": {"parse": 1.234}})
    return r


class TestToRows:
    def test_header_and_one_row_per_document(self, report):
        header, rows = report.to_rows()
        assert len(rows) == 2
        assert header[0] == "document"
        assert {r[0] for r in rows} == {"a.pdf", "b.pdf"}

    def test_every_cell_is_a_string(self, report):
        """So a CSV writer, a Sheets client and a DataFrame all just work."""
        _, rows = report.to_rows()
        assert all(isinstance(cell, str) for row in rows for cell in row)

    def test_columns_are_sorted_so_diffs_are_stable(self, report):
        header, _ = report.to_rows()
        record_cols = header[3:-2]
        assert record_cols == sorted(record_cols)

    def test_a_field_missing_on_one_document_is_empty_not_absent(self, report):
        """Every row has the same width, or nothing downstream can read it."""
        header, rows = report.to_rows()
        assert len({len(r) for r in rows}) == 1
        assert len(rows[0]) == len(header)

    def test_it_carries_the_context_a_reviewer_needs(self, report):
        header, rows = report.to_rows()
        by_doc = dict(zip([r[0] for r in rows], rows))
        assert by_doc["a.pdf"][header.index("jurisdiction")] == "NG"
        assert by_doc["a.pdf"][header.index("producer_family")] == "browser-print"
        assert "PII-3-EMAIL=1" in by_doc["a.pdf"][header.index("detections")]
        assert by_doc["a.pdf"][header.index("parse_seconds")] == "1.23"

    def test_an_abstained_jurisdiction_is_empty_not_the_word_none(self, report):
        header, rows = report.to_rows()
        by_doc = dict(zip([r[0] for r in rows], rows))
        assert by_doc["b.pdf"][header.index("jurisdiction")] == ""

    def test_an_empty_report_still_returns_a_header(self):
        header, rows = DocumentReport().to_rows()
        assert header and rows == []


class TestMasking:
    def test_masked_by_default(self, report):
        _, rows = report.to_rows()
        flat = " ".join(cell for row in rows for cell in row)
        assert "amara@example.com" not in flat
        assert "Amara Nwosu" not in flat

    def test_reveal_returns_the_real_values(self, report):
        _, rows = report.to_rows(reveal=True)
        flat = " ".join(cell for row in rows for cell in row)
        assert "amara@example.com" in flat

    def test_structural_columns_are_never_masked(self, report):
        """Jurisdiction and producer are not personal data and are useful."""
        header, rows = report.to_rows()
        by_doc = dict(zip([r[0] for r in rows], rows))
        assert by_doc["a.pdf"][header.index("jurisdiction")] == "NG"


class TestToCsv:
    def test_it_round_trips_through_a_csv_reader(self, report):
        text = report.to_csv()
        parsed = list(csv.reader(io.StringIO(text)))
        header, rows = report.to_rows()
        assert parsed[0] == header
        assert len(parsed) == len(rows) + 1

    def test_writing_to_a_path_returns_the_path(self, report, tmp_path):
        out = report.to_csv(tmp_path / "report.csv")
        assert out.exists()
        assert out.read_text(encoding="utf-8-sig").startswith("document,")

    def test_excel_encoding(self, report, tmp_path):
        """utf-8-sig, because Excel mangles non-ASCII names without the BOM.

        For this project's data that is most of them.
        """
        out = report.to_csv(tmp_path / "report.csv")
        assert out.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_csv_is_masked_by_default_too(self, report):
        assert "amara@example.com" not in report.to_csv()
        assert "amara@example.com" in report.to_csv(reveal=True)


class TestEveryExporterMasks:
    """A newly added exporter must opt into masking, or this fails.

    Enumerated by introspection rather than listed by hand, so the test keeps
    working when someone adds `to_parquet` and forgets.
    """

    def test_no_public_exporter_leaks_by_default(self, report):
        leaked = []
        for name in dir(report):
            if not name.startswith("to_"):
                continue
            method = getattr(report, name)
            if not callable(method):
                continue
            try:
                output = str(method())
            except TypeError:
                continue
            if "amara@example.com" in output or "Amara Nwosu" in output:
                leaked.append(name)
        assert not leaked, f"these exporters leak unmasked values: {leaked}"
