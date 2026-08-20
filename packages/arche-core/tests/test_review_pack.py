# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for `review_pack`, the export a reviewer adjudicates.

The contract this has to keep is not with arche, it is with
`tools/arche-studio`, which reads the pack back. Three things in particular:

* a `decision_id` column, because the studio digests it to notice an edited pack
* two column families sharing an underscore prefix, because that is how the
  studio works out which fields belong to which record without configuration
* the same outcome vocabulary the studio's store will accept on write

A pack that breaks any of the three loads but cannot be reviewed.
"""

from __future__ import annotations

import csv
import json

import pytest
from arche.report import PACK_SCHEMA, REVIEW_FIELDS, REVIEW_OUTCOMES, review_pack
from arche.resolve import crosswalk

_A = [{"id": "a1", "name": "Amara Patel", "birth_date": "2016-06-28"},
      {"id": "a2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]
_B = [{"id": "a1", "name": "Amara Patel", "birth_date": "6/28/2016"},
      {"id": "a2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]


def _pack(tmp_path, **kw):
    res = crosswalk(_A, _B, entity="person", id_field="id")
    kw.setdefault("reveal", True)
    manifest = review_pack(res, _A, _B, out_dir=tmp_path / "p", entity="person", **kw)
    rows = list(csv.DictReader((tmp_path / "p" / "pack.csv").open(encoding="utf-8")))
    return manifest, rows


class TestTheStudioContract:

    def test_writes_both_files(self, tmp_path):
        _pack(tmp_path)
        assert (tmp_path / "p" / "pack.csv").exists()
        assert (tmp_path / "p" / "manifest.json").exists()

    def test_every_row_carries_a_decision_id(self, tmp_path):
        """The studio digests these to notice a pack edited underneath it."""
        _, rows = _pack(tmp_path)
        assert rows
        assert all(r["decision_id"] for r in rows)

    def test_two_sides_share_underscore_prefixes(self, tmp_path):
        """How the studio tells the two records apart, with no configuration."""
        _, rows = _pack(tmp_path, sides=("left", "right"))
        fields = list(rows[0].keys())
        assert len([f for f in fields if f.startswith("left_")]) >= 2
        assert len([f for f in fields if f.startswith("right_")]) >= 2

    def test_the_four_review_columns_are_present_and_empty(self, tmp_path):
        _, rows = _pack(tmp_path)
        for r in rows:
            assert all(r[f] == "" for f in REVIEW_FIELDS)

    def test_outcome_vocabulary_matches_the_studio_store(self, tmp_path):
        """Drift here produces packs whose outcomes the studio refuses."""
        from pathlib import Path
        state = (Path(__file__).resolve().parents[3]
                 / "tools" / "arche-studio" / "state.py")
        if not state.exists():
            pytest.skip("studio not present in this checkout")
        text = state.read_text(encoding="utf-8")
        for outcome in REVIEW_OUTCOMES:
            assert f'"{outcome}"' in text

    def test_manifest_records_what_was_run(self, tmp_path):
        manifest, rows = _pack(tmp_path)
        assert manifest["schema"] == PACK_SCHEMA
        assert manifest["rows"] == len(rows)
        assert manifest["entity"] == "person"
        assert manifest["pins"]["comparators_sha256"]
        assert len(manifest["decision_ids_sha256"]) == 64

    def test_manifest_is_valid_json_on_disk(self, tmp_path):
        _pack(tmp_path)
        loaded = json.loads(
            (tmp_path / "p" / "manifest.json").read_text(encoding="utf-8"))
        assert loaded["schema"] == PACK_SCHEMA


class TestWhatGoesInIt:

    def test_evidence_round_trips_as_json(self, tmp_path):
        _, rows = _pack(tmp_path)
        ev = json.loads(rows[0]["evidence"])
        assert "name" in ev

    def test_no_match_rows_are_left_out_by_default(self, tmp_path):
        """A queue of things the engine already rejected is not a queue."""
        manifest, _ = _pack(tmp_path)
        assert "no_match" not in manifest["decisions"]

    def test_a_wider_decisions_tuple_includes_them(self, tmp_path):
        res = crosswalk(_A, _B, entity="person", id_field="id")
        wide = review_pack(res, _A, _B, out_dir=tmp_path / "w", reveal=True,
                           decisions=("match", "review", "no_match"))
        narrow = review_pack(res, _A, _B, out_dir=tmp_path / "n", reveal=True)
        assert wide["rows"] >= narrow["rows"]

    def test_side_prefix_with_an_underscore_is_refused(self, tmp_path):
        """It would split in the wrong place and mis-assign every column."""
        res = crosswalk(_A, _B, entity="person", id_field="id")
        with pytest.raises(ValueError, match="underscore"):
            review_pack(res, _A, _B, out_dir=tmp_path / "x", reveal=True,
                        sides=("source_a", "source_b"))

    def test_two_identical_prefixes_are_refused(self, tmp_path):
        res = crosswalk(_A, _B, entity="person", id_field="id")
        with pytest.raises(ValueError, match="distinct"):
            review_pack(res, _A, _B, out_dir=tmp_path / "y", reveal=True,
                        sides=("a", "a"))


class TestDisclosure:
    """A pack is a file that gets copied around."""

    def test_masked_is_the_default(self, tmp_path):
        res = crosswalk(_A, _B, entity="person", id_field="id")
        manifest = review_pack(res, _A, _B, out_dir=tmp_path / "m")
        assert manifest["disclosure"] == "masked"

    def test_revealed_says_so_in_the_manifest(self, tmp_path):
        manifest, _ = _pack(tmp_path, reveal=True)
        assert manifest["disclosure"] == "revealed (working copy)"

    def test_masking_actually_changes_the_values(self, tmp_path):
        """Otherwise the flag is decoration."""
        res = crosswalk(_A, _B, entity="person", id_field="id")
        review_pack(res, _A, _B, out_dir=tmp_path / "m")
        review_pack(res, _A, _B, out_dir=tmp_path / "r", reveal=True)
        masked = (tmp_path / "m" / "pack.csv").read_text(encoding="utf-8")
        revealed = (tmp_path / "r" / "pack.csv").read_text(encoding="utf-8")
        assert "Amara Patel" in revealed
        assert masked != revealed

    def test_sensitive_row_ids_are_refused_in_masked_mode(self, tmp_path):
        """A masked pack that prints national IDs as row keys is a leak."""
        a = [{"id": "12345678901", "name": "Amara Patel"}]
        b = [{"id": "12345678901", "name": "Amara Patel"}]
        res = crosswalk(a, b, entity="person", id_field="id")
        with pytest.raises(ValueError, match="sensitive identifiers"):
            review_pack(res, a, b, out_dir=tmp_path / "s")

    def test_and_allowed_when_revealed_deliberately(self, tmp_path):
        a = [{"id": "12345678901", "name": "Amara Patel"}]
        b = [{"id": "12345678901", "name": "Amara Patel"}]
        res = crosswalk(a, b, entity="person", id_field="id")
        assert review_pack(res, a, b, out_dir=tmp_path / "s", reveal=True)["rows"]
