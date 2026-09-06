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
            _no_docling, "auto", _FakeRun(), extraction_backend="regex"
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
                        _one_bad, "NG", _FakeRun(), extraction_backend="regex")
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


# `arche.doc.parse` as an attribute is the *function*; the module of the same
# name is only reachable through sys.modules. Same collision as `arche.extract`.
def _parse_module():
    import sys

    import arche.doc.parse  # noqa: F401  -- ensures the module is loaded

    return sys.modules["arche.doc.parse"]


class TestPlainTextNeedsNoParser:
    """`.txt` and `.md` are read directly, installed extras or not.

    This is what lets a base install run the published `resolve_documents`
    example, and it is why that example broke in CI while passing here: this
    machine had docling, the runner did not.
    """

    def test_a_text_file_parses_with_docling_absent(self, tmp_path, monkeypatch):
        mod = _parse_module()
        monkeypatch.setattr(mod, "DOC_FEATURE_AVAILABLE", False)
        f = tmp_path / "note.txt"
        f.write_text("Fatima Abdullahi\nNIN 12345678901", encoding="utf-8")

        parsed = mod.parse(str(f))

        assert "Fatima Abdullahi" in parsed.text
        assert parsed.provenance["parser"] == "text"

    def test_the_parse_does_not_change_when_docling_is_present(self, tmp_path):
        """Same bytes, same text, whatever is installed.

        A parse that varied with the environment would make `parser` in the
        provenance a description of the machine rather than of the extraction.
        """
        mod = _parse_module()
        f = tmp_path / "note.txt"
        f.write_text("Fatima Abdullahi", encoding="utf-8")

        assert mod.parse(str(f)).provenance["parser"] == "text"

    def test_a_pdf_still_needs_docling(self, tmp_path, monkeypatch):
        """The plain-text path must not swallow the missing-parser error."""
        mod = _parse_module()
        monkeypatch.setattr(mod, "DOC_FEATURE_AVAILABLE", False)
        f = tmp_path / "scan.pdf"
        f.write_bytes(b"%PDF-1.4\n")

        with pytest.raises(DoclingNotInstalledError):
            mod.parse(str(f))

    def test_undecodable_bytes_fall_through_rather_than_guess(
        self, tmp_path, monkeypatch
    ):
        """A `.txt` that is not UTF-8 is a real conversion problem.

        Guessing an encoding would put a silent mojibake rendering under a
        signature, so it goes to docling -- and says so when docling is absent.
        """
        mod = _parse_module()
        monkeypatch.setattr(mod, "DOC_FEATURE_AVAILABLE", False)
        f = tmp_path / "latin1.txt"
        f.write_bytes(b"Fatima Abdullahi \xff\xfe caf\xe9")

        with pytest.raises(DoclingNotInstalledError):
            mod.parse(str(f))

    def test_resolve_documents_reads_a_folder_of_text(self, tmp_path, monkeypatch):
        """The end the CI failure was actually about."""
        from arche import resolve_documents

        mod = _parse_module()
        monkeypatch.setattr(mod, "DOC_FEATURE_AVAILABLE", False)
        for name, text in {
            "statement.txt": "Fatima Abdullahi\nNIN 12345678901\nPhone 08031234567",
            "invoice.txt": "Fatuma Abdulahi\nNIN 12345678901\nPhone 08031234567",
        }.items():
            (tmp_path / name).write_text(text, encoding="utf-8")

        report = resolve_documents(
            str(tmp_path),
            jurisdiction="NG",
            quiet=True,
            progress=False,
            extraction_backend="regex",
        )

        assert len(report.records) == 2
        assert not report.errors
