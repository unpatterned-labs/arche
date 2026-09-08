# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The studio's Explain pane: a recorded decision by its id.

Three answers the CLI already gives -- ``decision``, ``explain``, ``replay`` --
on one screen, masked unless asked. The tests record decisions through the
library, then read them back through the studio handler exactly as the page
would.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("duckdb")

import arche  # noqa: E402

A = {"name": "Adaeze Okonkwo", "phone": "+2348031234567", "email": "adaeze@example.com"}
B = {"name": "Adaeze Okonkwo", "phone": "0803 123 4567"}
TEXT = "Adaeze Okonkwo, NIN 12345678901, phone +234 803 123 4567."


@pytest.fixture(scope="module")
def studio():
    return importlib.import_module("arche._studio")


@pytest.fixture()
def book(tmp_path, studio, monkeypatch):
    """A fresh ledger with one match and one redaction, attached to the studio."""
    path = tmp_path / "decisions.duckdb"
    with arche.attach(f"duckdb:///{path}") as ledger:
        matched = arche.compare(A, B, jurisdiction="NG", store=ledger)
        masked = arche.deidentify(TEXT, "NG", backend="basic", store=ledger)
    monkeypatch.setattr(studio, "LEDGER_URI", str(path))
    monkeypatch.setattr(studio, "_LEDGER", {})
    return {"match": matched.decision_id, "redaction": masked.decision_id}


class TestWithoutALedger:
    def test_status_says_so(self, studio, monkeypatch):
        monkeypatch.setattr(studio, "LEDGER_URI", None)
        assert studio._ledger_status() == {"attached": False, "uri": None}

    def test_explain_names_the_fix(self, studio, monkeypatch):
        monkeypatch.setattr(studio, "LEDGER_URI", None)
        with pytest.raises(ValueError, match="--ledger|ARCHE_LEDGER"):
            studio._explain("dec:sha256:anything")

    def test_the_flag_sets_it(self, studio, monkeypatch, tmp_path):
        """`--ledger` reaches the module the way the CLI passes it."""
        monkeypatch.setattr(studio, "LEDGER_URI", None)
        monkeypatch.setattr(studio, "Studio", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
        studio.main(["--ledger", str(tmp_path / "x.duckdb"), "--no-browser", "--port", "1"])
        assert studio.LEDGER_URI == str(tmp_path / "x.duckdb")


class TestAMatch:
    def test_what_why_and_whether_it_holds(self, studio, book):
        x = studio._explain(book["match"])
        assert x["decision"]["identity"] == "same_entity"
        assert x["decision"]["verb"] == "compare"
        assert set(x["why"]) >= {"supporting", "refuting", "missing", "shared"}
        assert "phone" in x["why"]["supporting"]
        assert x["replay"]["reproduced"] is True
        assert len(x["records"]) == 2

    def test_values_are_masked_until_asked(self, studio, book):
        masked = studio._explain(book["match"])
        assert "Adaeze Okonkwo" not in str(masked)
        assert "adaeze@example.com" not in str(masked)
        shown = studio._explain(book["match"], reveal=True)
        assert "Adaeze Okonkwo" in str(shown["records"])
        assert shown["reveal"] is True

    def test_an_unknown_id_is_a_readable_error(self, studio, book):
        with pytest.raises(ValueError, match="no decision"):
            studio._explain("dec:sha256:0000")

    def test_a_blank_id_is_too(self, studio, book):
        with pytest.raises(ValueError, match="paste"):
            studio._explain("   ")

    def test_the_route_answers(self, studio, book):
        """The handler behind `/api/explain`, through the same query parsing."""
        from urllib.parse import parse_qs
        q = parse_qs(f"id={book['match']}&reveal=1")
        x = studio._explain(q["id"][0], reveal=q["reveal"][0] in ("1", "true"))
        assert x["reveal"] is True


class TestARedaction:
    def test_spans_with_citations_and_never_a_value(self, studio, book):
        x = studio._explain(book["redaction"])
        assert x["decision"]["verb"] == "deidentify"
        assert x["why"]["verb"] == "deidentify"
        spans = x["why"]["spans"]
        assert spans and all({"category", "start", "end", "citation"} <= set(s) for s in spans)
        assert x["why"]["citations"]
        assert x["records"] == []
        dumped = str(x)
        assert "12345678901" not in dumped
        assert "Adaeze" not in dumped

    def test_replay_finds_the_same_spans_today(self, studio, book):
        assert studio._explain(book["redaction"])["replay"]["reproduced"] is True


class TestThePage:
    """The pane is wired the way every other pane is; the structural tests in
    test_studio_loads cover the tab, section and ids. These pin what is
    specific to explain."""

    @pytest.fixture(scope="class")
    def page(self, studio):
        from pathlib import Path
        return (Path(studio.__file__).parent / "index.html").read_text(encoding="utf-8")

    def test_the_deep_link_opens_the_pane(self, page):
        assert 'explain=([^&]+)' in page and 'tab("explain")' in page

    def test_the_identity_vocabulary_maps_onto_the_verdict_colours(self, page):
        for identity in ("same_entity", "review", "different", "deidentified"):
            assert f"{identity}:" in page
