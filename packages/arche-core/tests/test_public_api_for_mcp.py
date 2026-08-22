# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The functions `arche-mcp` depends on, promoted out of private modules.

Publishing a package freezes everything it imports. `arche-mcp` reached into
`arche.cli._load_records` and `arche.resolve._matcher.compare_names`, which
meant arche-core could no longer rename either without breaking a released
artifact — and a version pin does not help, because a *patch* release could do
it. Private names are private precisely so they can move.

The two cases needed different fixes.

`compare_names` was already public-shaped: no leading underscore, a stable
signature, a documented return. Only its address was private. Re-exporting it
is the whole change.

`_load_records` could not be re-exported. It raises `SystemExit` on bad input,
which is right for a command somebody typed and wrong for a library, where it
cannot be caught by anything reasonable and terminates a server. So the general
reader that already existed inside `arche.review` was promoted instead, and it
raises a catchable error.

These tests exist to make the promotion load-bearing rather than decorative: if
somebody deletes the public alias, this fails before a published package does.
"""

from __future__ import annotations

import json

import pytest


class TestCompareNames:

    def test_it_is_reachable_without_a_private_import(self):
        from arche.resolve import compare_names
        assert callable(compare_names)

    @pytest.mark.parametrize("a,b", [
        ("Mamadou Diallo", "Mohamed Jallow"),
        ("Adaeze Okonkwo", "Adaeze Okonkwo"),
        ("John Evelyn Smith", "John Smith"),
    ])
    def test_the_public_alias_returns_what_the_private_one_does(self, a, b):
        """An alias that drifted from its target would be worse than none."""
        from arche.resolve import compare_names
        from arche.resolve._matcher import compare_names as private
        assert compare_names(a, b) == private(a, b)

    def test_it_returns_similarity_and_u_probability(self):
        from arche.resolve import compare_names
        similarity, u = compare_names("Adaeze Okonkwo", "Adaeze Okonkwo")
        assert similarity == 1.0
        assert 0.0 <= u <= 1.0

    def test_priors_still_pass_through(self):
        from arche.resolve import compare_names
        assert compare_names("Mamadou Diallo", "Mohamed Jallow", None)


class TestReadRecords:

    @pytest.fixture
    def files(self, tmp_path):
        (tmp_path / "p.csv").write_text("id,name\n1,Adaeze\n", encoding="utf-8")
        (tmp_path / "p.jsonl").write_text(
            json.dumps({"id": "1", "name": "Adaeze"}) + "\n", encoding="utf-8")
        (tmp_path / "p.json").write_text(
            json.dumps([{"id": "1", "name": "Adaeze"}]), encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize("name", ["p.csv", "p.jsonl", "p.json"])
    def test_every_format_reads_the_same(self, files, name):
        from arche.review import read_records
        rows, fields = read_records(files / name)
        assert rows == [{"id": "1", "name": "Adaeze"}]
        assert fields == ["id", "name"]

    def test_a_missing_file_raises_something_catchable(self, tmp_path):
        """The reason this exists rather than exporting `_load_records`.

        `SystemExit` inherits from `BaseException`, so a bare `except
        Exception` does not catch it and an MCP server handling a bad path
        would exit rather than return an error to the agent.
        """
        from arche.review import PackError, read_records
        with pytest.raises(PackError):
            read_records(tmp_path / "nope.csv")

    def test_and_it_is_not_a_systemexit(self, tmp_path):
        from arche.review import read_records
        try:
            read_records(tmp_path / "nope.csv")
        except SystemExit:  # pragma: no cover - the thing being prevented
            pytest.fail("read_records raised SystemExit, which a library must not")
        except Exception:
            pass

    def test_an_unreadable_format_is_refused_by_name(self, tmp_path):
        from arche.review import PackError, read_records
        (tmp_path / "p.xlsx").write_bytes(b"PK\x03\x04")
        with pytest.raises(PackError, match="no reader for"):
            read_records(tmp_path / "p.xlsx")

    def test_it_is_read_pack_without_the_pack_checks(self, files):
        """`read_pack` reports `no-decision-id` on a plain record file, which is
        correct for an adjudication pack and noise for a list of people."""
        from arche.review import read_pack, read_records
        rows, _fields = read_records(files / "p.csv")
        pack = read_pack(files / "p.csv")
        assert pack.rows == rows
        assert any(p.code == "no-decision-id" for p in pack.problems)


def test_neither_private_name_is_needed_any_more():
    """The point of the exercise, stated as a test.

    If a future `arche-mcp` reintroduces a private import, this does not catch
    it — but it does prove the public route exists, so there is no excuse.
    """
    from arche.resolve import compare_names
    from arche.review import read_records
    assert compare_names.__module__.startswith("arche.resolve")
    assert read_records.__module__ == "arche.review"
