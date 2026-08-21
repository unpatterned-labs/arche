# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Reading a pack back, and binding outcomes to it.

`review_pack` shipped in the wheel and nothing that could read a pack did, so a
caller who exported their own data had a CSV, a manifest, and no supported way to
work them. The only consumer was a local web tool you got by cloning the repo.

`arche.review` supplies the artifact protocol and not the reviewing: read a pack,
check it is the one the matcher wrote, apply outcomes somebody arrived at however
they liked, and get an adjudication that can be re-checked. The human part stays
in a spreadsheet, a notebook, or a queue, and none of those become arche's
problem.

What these tests guard is the pair of bindings an auditor depends on: an
adjudication is bound to the CONTENT of the pack it was made against, and each
outcome is bound to a decision id.
"""

from __future__ import annotations

import csv
import json

import pytest
from arche.report import review_pack
from arche.resolve import crosswalk
from arche.review import (
    ADJUDICATION_SCHEMA,
    PackError,
    apply_outcomes,
    read_pack,
    validate_pack,
    verify_adjudication,
    write_reviewed_csv,
)

_RECORDS = [{"id": str(i), "name": n, "birth_date": d}
            for i, (n, d) in enumerate(
                [("Amara Patel", "2016-06-28"),
                 ("Malik Okonkwo", "2017-08-18"),
                 ("Ngozi Adeyemi", "1990-03-02")])]


@pytest.fixture
def packdir(tmp_path):
    res = crosswalk(_RECORDS, _RECORDS, entity="person", id_field="id")
    review_pack(res, _RECORDS, _RECORDS, out_dir=tmp_path / "p",
                entity="person", reveal=True)
    return tmp_path / "p"


def _outcomes(packdir, path, outcome="same_entity", reviewer="dee"):
    ids = read_pack(packdir).decision_ids
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["decision_id", "outcome",
                                                "reviewer", "reason"])
        writer.writeheader()
        for did in ids:
            writer.writerow({"decision_id": did, "outcome": outcome,
                             "reviewer": reviewer, "reason": "test"})
    return path


def _corrupt_a_name(packdir):
    path = packdir / "pack.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    fields = list(rows[0])
    rows[0][next(f for f in fields if f.endswith("_name"))] = "SOMEONE ELSE"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TestReadingAPack:

    def test_a_directory_works_as_well_as_the_csv(self, packdir):
        assert read_pack(packdir).path.name == "pack.csv"
        assert read_pack(packdir / "pack.csv").rows

    def test_a_clean_pack_has_no_problems(self, packdir):
        assert validate_pack(packdir)["ok"] is True
        assert validate_pack(packdir)["problems"] == []

    def test_a_missing_pack_raises_rather_than_reporting(self, tmp_path):
        """Nothing to check is different from something that checks badly."""
        with pytest.raises(PackError, match="no pack at"):
            read_pack(tmp_path / "nope")

    def test_validate_never_raises(self, tmp_path):
        report = validate_pack(tmp_path / "nope")
        assert report["ok"] is False
        assert report["problems"][0]["code"] == "unreadable"

    def test_an_edited_pack_is_caught(self, packdir):
        _corrupt_a_name(packdir)
        report = validate_pack(packdir)
        assert report["ok"] is False
        assert any(p["code"] == "content-digest-mismatch"
                   for p in report["problems"])

    def test_a_missing_manifest_warns_without_failing(self, packdir):
        (packdir / "manifest.json").unlink()
        report = validate_pack(packdir)
        assert report["ok"] is True, "a missing manifest is not a broken pack"
        assert any(p["code"] == "manifest-missing" for p in report["problems"])

    def test_duplicate_decision_ids_are_an_error(self, tmp_path):
        """The old id digest sorted before hashing, so a duplicate was invisible.

        An outcome for a duplicated id is ambiguous by construction.
        """
        path = tmp_path / "pack.csv"
        path.write_text("decision_id,a_name\nd1,x\nd1,y\n", encoding="utf-8")
        report = validate_pack(path)
        assert report["ok"] is False
        assert any(p["code"] == "duplicate-decision-id"
                   for p in report["problems"])


class TestApplyingOutcomes:

    def test_produces_an_adjudication_bound_to_the_pack(self, packdir, tmp_path):
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        assert adj["schema"] == ADJUDICATION_SCHEMA
        assert adj["marked"] == 3
        assert adj["source_pack_content_sha256"] == read_pack(packdir).content_digest

    def test_a_filled_in_pack_works_as_an_outcomes_file(self, packdir, tmp_path):
        """`review_outcome` is accepted as an alias for `outcome`.

        The four review columns a pack already carries ARE this schema, so
        somebody who filled the pack in directly should not have to rename
        anything.
        """
        path = packdir / "pack.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        fields = list(rows[0])
        for row in rows:
            row["review_outcome"] = "different"
            row["reviewer"] = "dee"
        filled = tmp_path / "filled.csv"
        with filled.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        assert apply_outcomes(packdir, filled)["outcomes"] == {"different": 3}

    def test_jsonl_works_too(self, packdir, tmp_path):
        ids = read_pack(packdir).decision_ids
        path = tmp_path / "o.jsonl"
        path.write_text("\n".join(json.dumps(
            {"decision_id": d, "outcome": "unresolved", "reviewer": "dee"})
            for d in ids), encoding="utf-8")
        assert apply_outcomes(packdir, path)["marked"] == 3

    def test_an_unknown_decision_id_is_refused(self, packdir, tmp_path):
        path = tmp_path / "o.csv"
        path.write_text(
            "decision_id,outcome,reviewer\nnot-in-pack,same_entity,dee\n",
            encoding="utf-8")
        with pytest.raises(PackError, match="not in this pack"):
            apply_outcomes(packdir, path)

    def test_an_outcome_outside_the_vocabulary_is_refused(self, packdir, tmp_path):
        path = _outcomes(packdir, tmp_path / "o.csv", outcome="probably?")
        with pytest.raises(PackError, match="not one of"):
            apply_outcomes(packdir, path)

    def test_an_unattributed_outcome_is_refused(self, packdir, tmp_path):
        """The same rule the studio enforces at its save button."""
        path = _outcomes(packdir, tmp_path / "o.csv", reviewer="")
        with pytest.raises(PackError, match="cannot be audited"):
            apply_outcomes(packdir, path)

    def test_a_dirty_pack_is_refused_by_default(self, packdir, tmp_path):
        path = _outcomes(packdir, tmp_path / "o.csv")
        _corrupt_a_name(packdir)
        with pytest.raises(PackError, match="cannot be identified"):
            apply_outcomes(packdir, path)

    def test_and_can_be_overridden_deliberately(self, packdir, tmp_path):
        path = _outcomes(packdir, tmp_path / "o.csv")
        _corrupt_a_name(packdir)
        assert apply_outcomes(packdir, path,
                              require_clean_pack=False)["marked"] == 3

    def test_unmarked_rows_are_counted_not_refused(self, packdir, tmp_path):
        ids = read_pack(packdir).decision_ids
        path = tmp_path / "o.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["decision_id", "outcome",
                                                    "reviewer"])
            writer.writeheader()
            writer.writerow({"decision_id": ids[0], "outcome": "same_entity",
                             "reviewer": "dee"})
            writer.writerow({"decision_id": ids[1], "outcome": "",
                             "reviewer": ""})
        adj = apply_outcomes(packdir, path)
        assert (adj["marked"], adj["unmarked"]) == (1, 2)


class TestVerifying:

    def test_a_fresh_adjudication_verifies(self, packdir, tmp_path):
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        report = verify_adjudication(adj, packdir)
        assert report["ok"] and report["outcomes_match"] and report["pack_matches"]

    def test_an_edited_ledger_is_caught(self, packdir, tmp_path):
        """A valid signature over the wrong ledger is what this exists to catch."""
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        adj["ledger"][0]["outcome"] = "different"
        report = verify_adjudication(adj, packdir)
        assert report["ok"] is False
        assert any(p["code"] == "ledger-digest-mismatch"
                   for p in report["problems"])

    def test_a_pack_edited_after_adjudication_is_caught(self, packdir, tmp_path):
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        _corrupt_a_name(packdir)
        report = verify_adjudication(adj, packdir)
        assert report["ok"] is False
        assert report["pack_matches"] is False

    def test_the_pack_is_optional(self, packdir, tmp_path):
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        report = verify_adjudication(adj)
        assert report["ok"] is True
        assert report["pack_checked"] is False

    def test_it_reads_from_a_path_too(self, packdir, tmp_path):
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        path = tmp_path / "adj.json"
        path.write_text(json.dumps(adj), encoding="utf-8")
        assert verify_adjudication(path, packdir)["ok"] is True


class TestTheReviewedCsv:

    def test_fills_the_columns_without_touching_the_pack(self, packdir, tmp_path):
        before = (packdir / "pack.csv").read_text(encoding="utf-8")
        adj = apply_outcomes(packdir, _outcomes(packdir, tmp_path / "o.csv"))
        out = write_reviewed_csv(packdir, adj, tmp_path / "reviewed.csv")
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert all(r["review_outcome"] == "same_entity" for r in rows)
        assert all(r["reviewer"] == "dee" for r in rows)
        assert (packdir / "pack.csv").read_text(encoding="utf-8") == before
