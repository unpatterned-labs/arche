# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A missing parser is not a folder full of unreadable documents.

`resolve_documents` treats a bad file as non-fatal, which is right: one
unreadable scan in a folder of twenty should not cost the other nineteen.

Without `docling` installed, though, *every* document fails identically and the
report comes back with zero records and N copies of one install error. From
outside that is indistinguishable from a folder of documents containing
nothing -- and the difference between "cannot read" and "read, found nothing"
is the whole value of the answer.
"""

from __future__ import annotations

import pytest

from arche.doc.parse import DoclingNotInstalledError


def _pdfs(tmp_path):
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4\n")
    return tmp_path


def test_an_absent_parser_raises_rather_than_returning_an_empty_report(
    tmp_path, monkeypatch
):
    from arche.doc import _documents

    def _no_docling(*args, **kwargs):
        raise DoclingNotInstalledError()

    monkeypatch.setattr("arche.doc.parse", _no_docling, raising=False)
    monkeypatch.setattr(_documents, "_collect", _documents._collect)

    with pytest.raises(DoclingNotInstalledError):
        _documents._collect(
            _documents.DocumentReport(), list(_pdfs(tmp_path).glob("*.pdf")),
            _no_docling, "auto", _FakeRun(),
        )


def test_one_bad_file_is_still_not_fatal(tmp_path):
    # The behaviour the raise above must not damage. A file that fails for its
    # own reasons is recorded and skipped; the run continues.
    from arche.doc import _documents

    calls = {"n": 0}

    def _one_bad(path):
        calls["n"] += 1
        if "b.pdf" in str(path):
            raise ValueError("corrupt")
        return _FakeParsed("Dennis Irorere, 12 Zaria Road, Kano")

    report = _documents.DocumentReport()
    _documents._collect(report, sorted(_pdfs(tmp_path).glob("*.pdf")),
                        _one_bad, "NG", _FakeRun())
    assert calls["n"] == 3, "the run stopped early on a bad file"
    assert "b.pdf" in report.errors
    assert "ValueError" in report.errors["b.pdf"]


class _FakeRun:
    def emit(self, *a, **k):
        pass

    def stage(self, *a, **k):
        pass


class _FakeParsed:
    def __init__(self, text):
        self.text = text
        self.info = None
