# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A pack is a document, not a CSV.

`read_pack` was CSV-only, which pushed every other format onto the caller. The
studio wrote its own `csv.DictReader` and could not open a parquet pack at all;
anybody with a pipeline that ends in parquet — which is most of them — had to
convert before they could review.

The interesting requirement is not that the formats parse. It is that they
**agree**: the same pack written three ways has to produce one content digest,
or an adjudication made against the parquet copy will not verify against the
CSV copy and the integrity check becomes a coin toss about file format.

That is what most of this file asserts. Typed formats are narrowed to strings on
read, deliberately, because the digest and the whole pack contract are defined
over the untyped representation CSV forced on the original design.
"""

from __future__ import annotations

import json

import pytest
from arche.report import review_pack
from arche.resolve import reconcile
from arche.review import PackError, read_pack

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

_RECORDS = [{"id": "r1", "name": "Adesola Okonkwo", "birth_date": "1990-03-02"},
            {"id": "r2", "name": "Adesola Okonkwo", "birth_date": "1990-03-02"},
            {"id": "r3", "name": "Malik Bello", "birth_date": "1988-01-09"}]


@pytest.fixture
def csv_pack(tmp_path):
    res = reconcile(_RECORDS, _RECORDS, entity="person", id_field="id")
    review_pack(res, _RECORDS, _RECORDS, out_dir=tmp_path / "csv",
                entity="person", sides=("reg", "sur"), reveal=True)
    return tmp_path / "csv"


@pytest.fixture
def typed_rows(csv_pack):
    """The CSV pack's rows, with the numeric columns as real numbers.

    This is the case that matters: not parquet in general, but parquet that
    kept the types CSV threw away.
    """
    rows = []
    for row in read_pack(csv_pack).rows:
        rec = dict(row)
        for key in ("score", "distinctive_max"):
            if rec.get(key) not in (None, ""):
                rec[key] = float(rec[key])
        rows.append(rec)
    return rows


class TestTheFormatsAgree:

    def test_parquet_digests_the_same_as_csv(self, csv_pack, typed_rows, tmp_path):
        out = tmp_path / "pq"
        out.mkdir()
        pq.write_table(pa.Table.from_pylist(typed_rows), out / "pack.parquet")
        assert read_pack(out).content_digest == read_pack(csv_pack).content_digest

    def test_jsonl_does_too(self, csv_pack, tmp_path):
        out = tmp_path / "jl"
        out.mkdir()
        with (out / "pack.jsonl").open("w", encoding="utf-8") as fh:
            for row in read_pack(csv_pack).rows:
                fh.write(json.dumps(row) + "\n")
        assert read_pack(out).content_digest == read_pack(csv_pack).content_digest

    def test_even_with_evidence_as_a_nested_object(self, csv_pack, tmp_path):
        """CSV has to serialise evidence as a string; JSONL does not have to.

        Both spellings mean the same thing, so both must digest the same, or a
        pipeline that wrote the natural JSON shape would produce a pack that
        failed its own check.
        """
        out = tmp_path / "jl"
        out.mkdir()
        with (out / "pack.jsonl").open("w", encoding="utf-8") as fh:
            for row in read_pack(csv_pack).rows:
                rec = dict(row)
                if rec.get("evidence"):
                    rec["evidence"] = json.loads(rec["evidence"])
                fh.write(json.dumps(rec) + "\n")
        assert read_pack(out).content_digest == read_pack(csv_pack).content_digest

    def test_the_fields_agree_in_order(self, csv_pack, typed_rows, tmp_path):
        out = tmp_path / "pq"
        out.mkdir()
        pq.write_table(pa.Table.from_pylist(typed_rows), out / "pack.parquet")
        assert read_pack(out).fields == read_pack(csv_pack).fields


class TestNormalisation:
    """What a typed cell becomes. Each of these was a way to break the digest."""

    @staticmethod
    def _one(tmp_path, value):
        path = tmp_path / "pack.jsonl"
        path.write_text(json.dumps({"decision_id": "d1", "v": value}) + "\n",
                        encoding="utf-8")
        return read_pack(path).rows[0]["v"]

    def test_a_whole_float_keeps_its_point(self, tmp_path):
        """1.0 must not become "1", or every score column would drift."""
        assert self._one(tmp_path, 1.0) == "1.0"

    def test_an_integer_does_not_gain_one(self, tmp_path):
        assert self._one(tmp_path, 3) == "3"

    def test_null_becomes_empty(self, tmp_path):
        assert self._one(tmp_path, None) == ""

    def test_a_bool_is_not_a_number(self, tmp_path):
        """`bool` is an `int` in Python, so True would otherwise render as 1."""
        assert self._one(tmp_path, True) == "true"

    def test_a_nested_object_is_canonical_json(self, tmp_path):
        assert self._one(tmp_path, {"b": 2, "a": 1}) == '{"a": 1, "b": 2}'


class TestChoosingTheFile:

    def test_a_directory_prefers_the_csv(self, csv_pack, typed_rows, tmp_path):
        """Both present is not an error; CSV wins because it is what
        `review_pack` writes and what a person can open in anything."""
        pq.write_table(pa.Table.from_pylist(typed_rows), csv_pack / "pack.parquet")
        assert read_pack(csv_pack).path.suffix == ".csv"

    def test_a_directory_with_only_parquet_works(self, typed_rows, tmp_path):
        out = tmp_path / "pq"
        out.mkdir()
        pq.write_table(pa.Table.from_pylist(typed_rows), out / "pack.parquet")
        assert read_pack(out).path.suffix == ".parquet"

    def test_a_differently_named_file_is_found(self, typed_rows, tmp_path):
        """So a directory holding `decisions.parquet` works without renaming."""
        out = tmp_path / "pq"
        out.mkdir()
        pq.write_table(pa.Table.from_pylist(typed_rows), out / "decisions.parquet")
        assert read_pack(out).path.name == "decisions.parquet"

    def test_an_empty_directory_says_what_it_wanted(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(PackError, match="no pack in"):
            read_pack(tmp_path / "empty")


class TestRefusals:

    def test_a_format_with_no_reader_is_refused_rather_than_sniffed(self, tmp_path):
        """A pack is re-read months later. A file whose format was guessed is a
        file whose reading cannot be reproduced."""
        path = tmp_path / "pack.xlsx"
        path.write_bytes(b"PK\x03\x04")
        with pytest.raises(PackError, match="no reader for"):
            read_pack(path)

    def test_a_broken_jsonl_line_names_the_line(self, tmp_path):
        path = tmp_path / "pack.jsonl"
        path.write_text('{"decision_id": "d1"}\nnot json\n', encoding="utf-8")
        with pytest.raises(PackError, match="line 2"):
            read_pack(path)

    def test_a_jsonl_row_that_is_not_an_object_is_refused(self, tmp_path):
        path = tmp_path / "pack.jsonl"
        path.write_text('{"decision_id": "d1"}\n[1, 2]\n', encoding="utf-8")
        with pytest.raises(PackError, match="has to be an object"):
            read_pack(path)

    def test_blank_lines_are_not_an_error(self, tmp_path):
        path = tmp_path / "pack.jsonl"
        path.write_text('{"decision_id": "d1"}\n\n{"decision_id": "d2"}\n',
                        encoding="utf-8")
        assert len(read_pack(path).rows) == 2


class TestRaggedInput:
    """Rows that do not all carry the same keys.

    Read rather than refused: a pipeline that omits empty columns is common and
    there is nothing ambiguous about it. The union of keys becomes the field
    list, and a row missing one gets the empty string, which is what the CSV
    spelling of the same pack would have held.
    """

    def test_the_field_list_is_the_union_in_first_seen_order(self, tmp_path):
        path = tmp_path / "pack.jsonl"
        path.write_text('{"decision_id": "d1", "a": "1"}\n'
                        '{"decision_id": "d2", "b": "2"}\n', encoding="utf-8")
        assert read_pack(path).fields == ["decision_id", "a", "b"]

    def test_a_missing_value_reads_as_empty(self, tmp_path):
        path = tmp_path / "pack.jsonl"
        path.write_text('{"decision_id": "d1", "a": "1"}\n'
                        '{"decision_id": "d2", "b": "2"}\n', encoding="utf-8")
        assert read_pack(path).rows[0]["b"] == ""


class TestJsonArrays:

    def test_a_bare_array_works(self, tmp_path):
        path = tmp_path / "pack.json"
        path.write_text(json.dumps([{"decision_id": "d1"}, {"decision_id": "d2"}]),
                        encoding="utf-8")
        assert len(read_pack(path).rows) == 2

    def test_so_does_an_object_with_rows(self, tmp_path):
        path = tmp_path / "pack.json"
        path.write_text(json.dumps({"rows": [{"decision_id": "d1"}]}),
                        encoding="utf-8")
        assert read_pack(path).decision_ids == ["d1"]

    def test_anything_else_says_what_it_wanted(self, tmp_path):
        path = tmp_path / "pack.json"
        path.write_text('{"nope": 1}', encoding="utf-8")
        with pytest.raises(PackError, match="does not hold a list of rows"):
            read_pack(path)
