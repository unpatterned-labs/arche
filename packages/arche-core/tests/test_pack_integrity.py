# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""What a review pack's digest actually covers.

An outside review of the review path found the manifest claiming more than it
delivered. `decision_ids_sha256` hashes the decision ids and nothing else, so it
notices a row added or dropped and misses every edit inside a row. Every name in
a pack could be rewritten and the digest still matched, while the guide around it
said "an edited pack is visible".

`pack_content_digest` covers content. These tests pin the four properties that
make it worth having, and the failure it was written to catch is
`test_editing_a_name_moves_it_while_the_id_list_does_not`.
"""

from __future__ import annotations

import csv

import pytest
from arche.report import REVIEW_FIELDS, pack_content_digest, review_pack
from arche.resolve import crosswalk

_A = [{"id": "1", "name": "Amara Patel", "birth_date": "2016-06-28"},
      {"id": "2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]
_B = [{"id": "1", "name": "Amara Patel", "birth_date": "6/28/2016"},
      {"id": "2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]


@pytest.fixture
def pack(tmp_path):
    res = crosswalk(_A, _B, entity="person", id_field="id")
    manifest = review_pack(res, _A, _B, out_dir=tmp_path / "p",
                           entity="person", reveal=True)
    return tmp_path / "p" / "pack.csv", manifest


def _read(path):
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return rows, list(rows[0].keys())


def _write(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TestTheContentDigest:

    def test_is_recomputable_from_the_csv_alone(self, pack):
        """The point of it. A reviewer who was not there can check the pack."""
        path, manifest = pack
        rows, fields = _read(path)
        assert pack_content_digest(rows, fields) == manifest["content_sha256"]

    def test_editing_a_name_moves_it_while_the_id_list_does_not(self, pack):
        """The failure the old digest could never see."""
        path, _ = pack
        rows, fields = _read(path)
        before = pack_content_digest(rows, fields)
        ids_before = sorted(r["decision_id"] for r in rows)

        name_col = next(f for f in fields if f.endswith("_name"))
        rows[0][name_col] = "SOMEBODY ELSE ENTIRELY"
        _write(path, rows, fields)

        after_rows, after_fields = _read(path)
        assert pack_content_digest(after_rows, after_fields) != before
        # and the id-membership digest would have been perfectly happy
        assert sorted(r["decision_id"] for r in after_rows) == ids_before

    def test_a_reviewer_doing_their_job_does_not_move_it(self, pack):
        """A digest that trips when somebody fills the form gets ignored."""
        path, _ = pack
        rows, fields = _read(path)
        before = pack_content_digest(rows, fields)
        for row in rows:
            row["review_outcome"] = "same_entity"
            row["reviewer"] = "dee"
            row["reason"] = "checked by hand"
        _write(path, rows, fields)
        assert pack_content_digest(*_read(path)) == before

    def test_a_dropped_row_moves_it(self, pack):
        path, _ = pack
        rows, fields = _read(path)
        before = pack_content_digest(rows, fields)
        _write(path, rows[:-1], fields)
        assert pack_content_digest(*_read(path)) != before

    def test_reordering_does_not_move_it(self, pack):
        """Sorting a pack in a spreadsheet is not tampering."""
        path, _ = pack
        rows, fields = _read(path)
        before = pack_content_digest(rows, fields)
        _write(path, list(reversed(rows)), fields)
        assert pack_content_digest(*_read(path)) == before

    def test_review_columns_are_excluded_by_name(self):
        rows = [{"decision_id": "d1", "score": "1.0",
                 **{f: "anything" for f in REVIEW_FIELDS}}]
        fields = list(rows[0])
        changed = [{**rows[0], **{f: "something else" for f in REVIEW_FIELDS}}]
        assert pack_content_digest(rows, fields) == pack_content_digest(
            changed, fields)


class TestTheManifestCarriesBoth:

    def test_content_and_membership_are_separate_fields(self, pack):
        _, manifest = pack
        assert len(manifest["content_sha256"]) == 64
        assert len(manifest["decision_ids_sha256"]) == 64
        assert manifest["content_sha256"] != manifest["decision_ids_sha256"]
