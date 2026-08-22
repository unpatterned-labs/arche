# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The masked projection of a pack, and what it must not carry.

A working pack is written with `reveal=True`, because a masked one cannot be
adjudicated: nobody can say whether two people are the same when both names are
redacted. So the reviewer's document holds real values by necessity, and every
path that copied it — the studio's save button, most obviously — carried them
onward.

`share_artifact` is the other artifact: computed from the working one, masked
through the same allowlist `review_pack` uses, with its own digest and a pointer
back to the source.

These tests are mostly negative. A masking function that works is not
interesting; a masking function that leaves one column, one sidecar or one free
text field unmasked is the entire failure mode, and it is invisible to anyone
reading the output casually. So the assertions look for the raw values
everywhere in the artifact rather than checking that the columns look masked.
"""

from __future__ import annotations

import json

import pytest
from arche.report import review_pack
from arche.resolve import crosswalk
from arche.review import PackError, read_pack, share_artifact

_NAME = "Adesola Okonkwo"
_EMAIL = "adesola@example.ng"

_RECORDS = [
    {"id": "r1", "name": _NAME, "birth_date": "1990-03-02", "email": _EMAIL},
    {"id": "r2", "name": _NAME, "birth_date": "1990-03-02", "email": _EMAIL},
    {"id": "r3", "name": "Malik Bello", "birth_date": "1988-01-09",
     "email": "malik@example.ng"},
]


@pytest.fixture
def packdir(tmp_path):
    res = crosswalk(_RECORDS, _RECORDS, entity="person", id_field="id")
    review_pack(res, _RECORDS, _RECORDS, out_dir=tmp_path / "p",
                entity="person", sides=("reg", "sur"), reveal=True)
    return tmp_path / "p"


@pytest.fixture
def adjudication(packdir):
    """One mark, with a reason that names the person. Deliberately."""
    did = read_pack(packdir).decision_ids[0]
    return {"ledger": [{"decision_id": did, "outcome": "same_entity",
                        "reviewer": "dee",
                        "reason": f"same person, {_NAME}, confirmed by phone",
                        "marked_at": "2026-08-21T00:00:00Z"}]}


def _everything_written(out_dir):
    """Every byte of the artifact: the CSV and the manifest, as one string."""
    return ((out_dir / "pack.csv").read_text(encoding="utf-8")
            + (out_dir / "manifest.json").read_text(encoding="utf-8"))


class TestWhatSurvives:

    def test_the_working_pack_does_carry_the_name(self, packdir):
        """The premise. If this ever stops being true the rest proves nothing."""
        assert _NAME in (packdir / "pack.csv").read_text(encoding="utf-8")

    def test_and_the_share_artifact_does_not(self, packdir, tmp_path):
        share_artifact(packdir, tmp_path / "s")
        assert _NAME not in _everything_written(tmp_path / "s")

    def test_nor_any_other_masked_value(self, packdir, tmp_path):
        share_artifact(packdir, tmp_path / "s")
        written = _everything_written(tmp_path / "s")
        for value in (_EMAIL, "1990-03-02", "Malik Bello"):
            assert value not in written, f"{value!r} survived masking"

    def test_the_decision_machinery_survives(self, packdir, tmp_path):
        """A score is not somebody's data, and a reader needs it."""
        share_artifact(packdir, tmp_path / "s")
        row = read_pack(tmp_path / "s").rows[0]
        assert row["decision"] in {"match", "review", "no_match"}
        assert float(row["score"]) >= 0.0
        assert row["decision_id"].startswith("xwd:sha256:")

    def test_the_ids_survive(self, packdir, tmp_path):
        """Otherwise the artifact cannot be joined back to anything."""
        share_artifact(packdir, tmp_path / "s")
        rows = read_pack(tmp_path / "s").rows
        assert {r["reg_id"] for r in rows} <= {"r1", "r2", "r3"}

    def test_the_evidence_survives(self, packdir, tmp_path):
        """Field names and per-field scores. No values in it."""
        share_artifact(packdir, tmp_path / "s")
        evidence = json.loads(read_pack(tmp_path / "s").rows[0]["evidence"])
        assert "name" in evidence


class TestTheReviewerReason:
    """Free text somebody typed, which can contain anything.

    Including the name the rest of the row just masked, which is what the
    fixture puts there. A detector over free text would miss it quietly, and
    quiet is the failure mode that matters, so the default is to drop it.
    """

    def test_it_is_dropped_by_default(self, packdir, tmp_path, adjudication):
        share_artifact(packdir, tmp_path / "s", adjudication=adjudication)
        assert "reason" not in read_pack(tmp_path / "s").fields
        assert _NAME not in _everything_written(tmp_path / "s")

    def test_the_outcome_and_reviewer_are_kept(self, packdir, tmp_path,
                                               adjudication):
        """Dropping the reason must not drop who decided what."""
        share_artifact(packdir, tmp_path / "s", adjudication=adjudication)
        marked = [r for r in read_pack(tmp_path / "s").rows
                  if r["review_outcome"]]
        assert len(marked) == 1
        assert marked[0]["reviewer"] == "dee"

    def test_it_can_be_kept_deliberately(self, packdir, tmp_path, adjudication):
        share_artifact(packdir, tmp_path / "s", adjudication=adjudication,
                       include_reasons=True)
        assert "reason" in read_pack(tmp_path / "s").fields
        assert _NAME in (tmp_path / "s" / "pack.csv").read_text(encoding="utf-8")

    def test_and_the_manifest_says_which_it_was(self, packdir, tmp_path,
                                                adjudication):
        """A reader should not have to diff the columns to find out."""
        assert share_artifact(packdir, tmp_path / "s",
                              adjudication=adjudication)["reasons_included"] is False
        assert share_artifact(packdir, tmp_path / "s2", adjudication=adjudication,
                              include_reasons=True)["reasons_included"] is True


class TestTheManifest:

    def test_it_has_its_own_digest_over_its_own_rows(self, packdir, tmp_path):
        """Not the source's. A manifest that describes a different file is worse
        than none, because it invites a check that passes for the wrong reason."""
        manifest = share_artifact(packdir, tmp_path / "s")
        assert read_pack(tmp_path / "s").content_digest == manifest["content_sha256"]
        assert manifest["content_sha256"] != manifest["source_pack_content_sha256"]

    def test_it_points_back_at_the_source(self, packdir, tmp_path):
        manifest = share_artifact(packdir, tmp_path / "s")
        assert (manifest["source_pack_content_sha256"]
                == read_pack(packdir).content_digest)

    def test_it_is_marked_as_masked(self, packdir, tmp_path):
        manifest = share_artifact(packdir, tmp_path / "s")
        assert manifest["schema"] == "arche.review_pack.shared.v1"
        assert "masked" in manifest["disclosure"]

    def test_a_changed_source_changes_the_pointer(self, packdir, tmp_path):
        """So an artifact cannot be passed off as derived from a pack it isn't."""
        first = share_artifact(packdir, tmp_path / "s")
        path = packdir / "pack.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("Malik", "Malick"),
                        encoding="utf-8")
        second = share_artifact(packdir, tmp_path / "s2")
        assert first["source_pack_content_sha256"] != second["source_pack_content_sha256"]


class TestRefusals:

    def test_an_id_that_looks_like_a_national_identifier_is_refused(self, tmp_path):
        """A masked pack still carries its ids, so a hot id column is a leak.

        The same rule `review_pack` applies in masked mode, applied here so the
        two cannot disagree about what masked means.
        """
        records = [{"id": "12345678901", "name": _NAME, "birth_date": "1990-03-02"},
                   {"id": "23456789012", "name": _NAME, "birth_date": "1990-03-02"}]
        res = crosswalk(records, records, entity="person", id_field="id")
        review_pack(res, records, records, out_dir=tmp_path / "p",
                    entity="person", sides=("reg", "sur"), reveal=True)
        with pytest.raises(PackError, match="sensitive identifiers"):
            share_artifact(tmp_path / "p", tmp_path / "s")

    def test_and_a_safe_id_column_can_be_named_instead(self, tmp_path):
        records = [{"id": "12345678901", "ref": "A1", "name": _NAME},
                   {"id": "23456789012", "ref": "A2", "name": _NAME}]
        res = crosswalk(records, records, entity="person", id_field="id")
        review_pack(res, records, records, out_dir=tmp_path / "p",
                    entity="person", sides=("reg", "sur"), reveal=True)
        share_artifact(tmp_path / "p", tmp_path / "s",
                       id_columns=["reg_ref", "sur_ref"])
        written = _everything_written(tmp_path / "s")
        assert "12345678901" not in written
        assert "A1" in written

    def test_a_missing_pack_raises(self, tmp_path):
        with pytest.raises(PackError, match="no pack at"):
            share_artifact(tmp_path / "nope", tmp_path / "s")


class TestTheSourceIsUntouched:

    def test_the_working_pack_is_not_rewritten(self, packdir, tmp_path):
        """This is a projection, not a redaction pass over the original.

        Masking in place would leave a manifest describing a file that no longer
        exists, and would destroy the document the reviewer was working from.
        """
        before = (packdir / "pack.csv").read_text(encoding="utf-8")
        manifest_before = (packdir / "manifest.json").read_text(encoding="utf-8")
        share_artifact(packdir, tmp_path / "s")
        assert (packdir / "pack.csv").read_text(encoding="utf-8") == before
        assert (packdir / "manifest.json").read_text(encoding="utf-8") == manifest_before

    def test_writing_inside_the_pack_directory_is_fine(self, packdir):
        """Where the studio puts it. The source must survive its own sibling."""
        before = (packdir / "pack.csv").read_text(encoding="utf-8")
        share_artifact(packdir, packdir / "pack_shared")
        assert (packdir / "pack.csv").read_text(encoding="utf-8") == before
        assert _NAME not in _everything_written(packdir / "pack_shared")
