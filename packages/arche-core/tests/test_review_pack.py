# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for `review_pack`, the export a reviewer adjudicates.

The contract this has to keep is not with arche, it is with
`arche studio` (`arche._studio`), which reads the pack back. Three things in particular:

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
from arche.resolve import reconcile

_A = [{"id": "a1", "name": "Amara Patel", "birth_date": "2016-06-28"},
      {"id": "a2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]
_B = [{"id": "a1", "name": "Amara Patel", "birth_date": "6/28/2016"},
      {"id": "a2", "name": "Malik Okonkwo", "birth_date": "2017-08-18"}]


def _pack(tmp_path, **kw):
    res = reconcile(_A, _B, entity="person", id_field="id")
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

        from arche._studio import state as studio_state
        text = Path(studio_state.__file__).read_text(encoding="utf-8")
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
        res = reconcile(_A, _B, entity="person", id_field="id")
        wide = review_pack(res, _A, _B, out_dir=tmp_path / "w", reveal=True,
                           decisions=("match", "review", "no_match"))
        narrow = review_pack(res, _A, _B, out_dir=tmp_path / "n", reveal=True)
        assert wide["rows"] >= narrow["rows"]

    def test_side_prefix_with_an_underscore_is_refused(self, tmp_path):
        """It would split in the wrong place and mis-assign every column."""
        res = reconcile(_A, _B, entity="person", id_field="id")
        with pytest.raises(ValueError, match="underscore"):
            review_pack(res, _A, _B, out_dir=tmp_path / "x", reveal=True,
                        sides=("source_a", "source_b"))

    def test_two_identical_prefixes_are_refused(self, tmp_path):
        res = reconcile(_A, _B, entity="person", id_field="id")
        with pytest.raises(ValueError, match="distinct"):
            review_pack(res, _A, _B, out_dir=tmp_path / "y", reveal=True,
                        sides=("a", "a"))


class TestDisclosure:
    """A pack is a file that gets copied around."""

    def test_masked_is_the_default(self, tmp_path):
        res = reconcile(_A, _B, entity="person", id_field="id")
        manifest = review_pack(res, _A, _B, out_dir=tmp_path / "m")
        assert manifest["disclosure"] == "masked"

    def test_revealed_says_so_in_the_manifest(self, tmp_path):
        manifest, _ = _pack(tmp_path, reveal=True)
        assert manifest["disclosure"] == "revealed (working copy)"

    def test_masking_actually_changes_the_values(self, tmp_path):
        """Otherwise the flag is decoration."""
        res = reconcile(_A, _B, entity="person", id_field="id")
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
        res = reconcile(a, b, entity="person", id_field="id")
        with pytest.raises(ValueError, match="sensitive identifiers"):
            review_pack(res, a, b, out_dir=tmp_path / "s")

    def test_and_allowed_when_revealed_deliberately(self, tmp_path):
        a = [{"id": "12345678901", "name": "Amara Patel"}]
        b = [{"id": "12345678901", "name": "Amara Patel"}]
        res = reconcile(a, b, entity="person", id_field="id")
        assert review_pack(res, a, b, out_dir=tmp_path / "s", reveal=True)["rows"]


class TestSharedEvidenceCarriesNoText:
    r"""A masked pack must not carry a name inside its evidence column.

    Found 2026-10-05. ``share_artifact`` copied every decision column verbatim
    on the reasoning that "a score is not somebody's data and a reader needs it
    to see what the matcher did", which is right about scores and wrong about
    ``evidence``: ``reconcile`` writes ``evidence["name_phrase"] = phrase``
    whenever the shared phrase is rarer than any shared token
    (``reconcile.py:539``), so the plaintext name travelled into the shared
    artifact in the same row where ``a_name`` and ``b_name`` read ``[NAME]``.

    The leak was correlated with how identifying the value was -- a phrase is
    written only when it is the rarest shared signal -- which is the worst
    correlation a leak of this kind can have. The manifest meanwhile stamped
    the file ``"disclosure": "masked (safe to share)"`` and the docstring
    promised "nothing raw survives anywhere in it ... not inside the evidence".
    """

    _NAME = "Chukwuemeka Obiorah"

    def _pack_with_text_evidence(self, tmp_path):
        """A pack whose evidence holds a name, which is what `name_phrase` is."""
        src = tmp_path / "src"
        src.mkdir()
        evidence = json.dumps({"name": 1.0,
                               "name_phrase": self._NAME.lower(),
                               "name_phrase_rarity": 0.994})
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score",
                             "distinctive_max", "a_id", "a_name", "b_id",
                             "b_name", "evidence", *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:feed", "match", "0.97", "0.96",
                             "p1", self._NAME, "p2", self._NAME, evidence,
                             *["" for _ in REVIEW_FIELDS]])
        return src / "pack.csv"

    def test_no_name_survives_inside_the_evidence(self, tmp_path):
        from arche.review import share_artifact
        share_artifact(self._pack_with_text_evidence(tmp_path),
                       tmp_path / "shared")
        shared = (tmp_path / "shared" / "pack.csv").read_text(
            encoding="utf-8").lower()
        for token in self._NAME.lower().split():
            assert token not in shared

    def test_the_measurements_do_survive(self, tmp_path):
        """Masking the text must not cost the numbers a reader needs."""
        from arche.review import share_artifact
        share_artifact(self._pack_with_text_evidence(tmp_path),
                       tmp_path / "shared")
        with (tmp_path / "shared" / "pack.csv").open(encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        evidence = json.loads(row["evidence"])
        assert evidence["name"] == 1.0
        assert evidence["name_phrase_rarity"] == 0.994
        # The key survives with its value replaced: *that* a phrase drove this
        # match is legitimate signal, what the phrase said is not.
        assert evidence["name_phrase"] == "[VALUE]"

    def test_unparseable_evidence_is_replaced_not_passed_through(self):
        """Evidence the masker cannot read is evidence it cannot vouch for."""
        from arche.review import _mask_evidence
        assert _mask_evidence("Chukwuemeka, not json") == "[VALUE]"
        assert _mask_evidence("") == ""
        assert _mask_evidence(None) is None

    def test_masking_is_by_type_not_by_key_name(self):
        """A string-valued evidence key added later is masked regardless."""
        from arche.review import _mask_evidence
        out = json.loads(_mask_evidence(json.dumps(
            {"some_future_key": "Ada Lovelace", "score": 0.5,
             "nested": {"deeper": "Grace Hopper", "n": 1}})))
        assert out["some_future_key"] == "[VALUE]"
        assert out["nested"]["deeper"] == "[VALUE]"
        assert out["score"] == 0.5
        assert out["nested"]["n"] == 1


class TestTheSharedArtifactCanBeVerified:
    """The artifact you send must be able to check the decisions it carries.

    ``decision_id`` is a content hash over the edge *and* the pins
    (``reconcile.py:975``). Until 2026-10-05 ``share_artifact``'s manifest
    omitted the pins, so a recipient held every decision address and could
    recompute none: the only artifact safe to share was the only one that could
    not be verified, which defeats the purpose of addressing a decision.

    The first test below is the whole claim -- *a second party can check a
    linkage decision without receiving the records* -- reduced to an assertion.
    """

    def test_a_decision_id_recomputes_from_the_shared_artifact_alone(
            self, tmp_path):
        """The claim, as a test. Nothing here touches the source records."""
        from arche.ids import content_hash
        from arche.review import read_pack, share_artifact

        res = reconcile(_A, _B, entity="person", id_field="id")
        review_pack(res, _A, _B, out_dir=tmp_path / "p", entity="person")
        share_artifact(tmp_path / "p" / "pack.csv", tmp_path / "s")

        shared = read_pack(tmp_path / "s" / "pack.csv")
        pins = shared.manifest["pins"]
        assert pins, "the shared manifest must carry the pins"
        assert shared.manifest["decision_ids_verifiable"] is True

        # Rebuild the edge from the SHARED row only, and rehash it.
        row = shared.rows[0]
        edge = {
            "a_id": row["a_id"],
            "b_id": row["b_id"],
            "score": float(row["score"]),
            "decision": row["decision"],
            "evidence": json.loads(row["evidence"]),
            "distinctive_max": float(row["distinctive_max"]),
        }
        recomputed = content_hash(
            {"schema": "arche.crosswalk_edge.v1", **edge, "pins": pins},
            prefix="xwd")
        assert recomputed == row["decision_id"]

        # And the artifact it was computed from holds no name.
        text = (tmp_path / "s" / "pack.csv").read_text(encoding="utf-8")
        assert "Amara" not in text

    def test_redacted_evidence_is_declared_unverifiable(self, tmp_path):
        """Masking a value changes what the id was computed over. Say so."""
        from arche.review import read_pack, share_artifact

        src = tmp_path / "src"
        src.mkdir()
        evidence = json.dumps({"name": 1.0, "name_phrase": "ada lovelace"})
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score",
                             "distinctive_max", "a_id", "a_name", "b_id",
                             "b_name", "evidence", *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:beef", "match", "0.9", "0.9", "p1",
                             "Ada Lovelace", "p2", "Ada Lovelace", evidence,
                             *["" for _ in REVIEW_FIELDS]])
        (src / "manifest.json").write_text(
            json.dumps({"schema": PACK_SCHEMA, "pins": {"engine": "x"}}),
            encoding="utf-8")

        share_artifact(src / "pack.csv", tmp_path / "s")
        manifest = read_pack(tmp_path / "s" / "pack.csv").manifest
        assert manifest["decision_ids_verifiable"] is False
        assert "redacted" in manifest["decision_ids_verifiable_note"]

    def test_a_pack_with_no_pins_says_so_rather_than_implying_verifiability(
            self, tmp_path):
        from arche.review import read_pack, share_artifact

        src = tmp_path / "src"
        src.mkdir()
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score", "a_id",
                             "a_name", "b_id", "b_name", *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:beef", "match", "0.9", "p1", "Ada",
                             "p2", "Ada", *["" for _ in REVIEW_FIELDS]])
        share_artifact(src / "pack.csv", tmp_path / "s")
        manifest = read_pack(tmp_path / "s" / "pack.csv").manifest
        assert manifest["decision_ids_verifiable"] is False
        assert "no pins" in manifest["decision_ids_verifiable_note"]

    def test_a_sensitive_looking_pin_is_refused(self, tmp_path):
        """Pins publish verbatim, so they get the row ids' scrutiny.

        `reconcile` accepts `extra_pins`, so a caller can put anything in one,
        and this artifact is stamped "safe to share".
        """
        from arche.review import PackError, share_artifact

        src = tmp_path / "src"
        src.mkdir()
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score", "a_id",
                             "a_name", "b_id", "b_name", *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:beef", "match", "0.9", "p1", "Ada",
                             "p2", "Ada", *["" for _ in REVIEW_FIELDS]])
        (src / "manifest.json").write_text(
            json.dumps({"schema": PACK_SCHEMA,
                        "pins": {"engine": "x", "case_ref": "12345678901"}}),
            encoding="utf-8")
        with pytest.raises(PackError, match="sensitive"):
            share_artifact(src / "pack.csv", tmp_path / "s")


class TestASecondPartyCanCheckTheDecisions:
    """`verify_decision_ids` is the check an outside party actually runs.

    The claim the pipeline rests on is that a linkage decision can be handed to
    somebody who does not have the records and does not trust the producer, and
    that they can check it. Re-deriving a ``decision_id`` required knowing it is
    a content hash over the edge plus the pins under a schema named in
    ``reconcile.py`` -- which meant the experiment could only be performed by
    someone who reads this source. That is not a second party, that is us.

    The tamper tests are the ones that matter. A verifier that returns ok for
    everything is worse than none, because it manufactures confidence.
    """

    def _sent(self, tmp_path):
        """Produce a pack, derive the masked artifact, return what you would send."""
        from arche.review import share_artifact
        res = reconcile(_A, _B, entity="person", id_field="id")
        review_pack(res, _A, _B, out_dir=tmp_path / "working", entity="person")
        share_artifact(tmp_path / "working" / "pack.csv", tmp_path / "to_send")
        return tmp_path / "to_send" / "pack.csv"

    def _retamper(self, sent, tmp_path, column, value):
        """The same artifact with one cell edited and the manifest untouched."""
        with sent.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys())
        rows[0][column] = value
        out = tmp_path / f"tampered_{column}"
        out.mkdir()
        with (out / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        (out / "manifest.json").write_text(
            (sent.parent / "manifest.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        return out / "pack.csv"

    def test_the_artifact_you_send_verifies(self, tmp_path):
        from arche.review import verify_decision_ids
        report = verify_decision_ids(self._sent(tmp_path))
        assert report["ok"] is True
        assert report["pins_present"] is True
        assert report["checked"] >= 1
        assert report["matched"] == report["checked"]
        assert report["mismatched"] == []

    def test_and_it_holds_no_source_values(self, tmp_path):
        """Verifiable and masked at the same time, which is the whole point."""
        text = self._sent(tmp_path).read_text(encoding="utf-8")
        for value in ("Amara", "Patel"):
            assert value not in text

    @pytest.mark.parametrize("column,value", [
        ("decision", "different"),
        ("score", "0.5"),
        ("evidence", '{"name": 0.1}'),
        ("distinctive_max", "0.1"),
    ])
    def test_an_edited_cell_is_caught(self, tmp_path, column, value):
        """Each of these would change the decision. None may pass."""
        from arche.review import verify_decision_ids
        sent = self._sent(tmp_path)
        report = verify_decision_ids(self._retamper(sent, tmp_path, column, value))
        assert report["ok"] is False
        assert len(report["mismatched"]) == 1
        assert any(p["code"] == "decision-id-mismatch" for p in report["problems"])

    def test_swapped_pins_are_caught(self, tmp_path):
        """Claiming a different threshold than the one that produced the verdict."""
        from arche.review import verify_decision_ids
        sent = self._sent(tmp_path)
        manifest_path = sent.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["pins"]["threshold"] = 0.123
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        report = verify_decision_ids(sent)
        assert report["ok"] is False
        assert report["matched"] == 0

    def test_a_pack_without_pins_is_told_what_to_ask_for(self, tmp_path):
        """Not verifiable is a different answer from not valid."""
        from arche.review import verify_decision_ids
        src = tmp_path / "nopins"
        src.mkdir()
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score",
                             "distinctive_max", "a_id", "b_id", "evidence",
                             *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:beef", "match", "0.9", "0.9", "p1",
                             "p2", "{}", *["" for _ in REVIEW_FIELDS]])
        report = verify_decision_ids(src / "pack.csv")
        assert report["ok"] is False
        assert report["pins_present"] is False
        assert report["checked"] == 0
        problem = next(p for p in report["problems"] if p["code"] == "no-pins")
        assert "pins" in problem["detail"]

    def test_redacted_evidence_refuses_rather_than_reporting_a_mismatch(
            self, tmp_path):
        """A redacted pack is unverifiable by construction, not corrupt."""
        from arche.review import share_artifact, verify_decision_ids
        src = tmp_path / "textev"
        src.mkdir()
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score",
                             "distinctive_max", "a_id", "a_name", "b_id",
                             "b_name", "evidence", *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:beef", "match", "0.9", "0.9", "p1",
                             "Ada Lovelace", "p2", "Ada Lovelace",
                             json.dumps({"name": 1.0, "name_phrase": "ada lovelace"}),
                             *["" for _ in REVIEW_FIELDS]])
        (src / "manifest.json").write_text(
            json.dumps({"schema": PACK_SCHEMA, "pins": {"engine": "x"}}),
            encoding="utf-8")
        share_artifact(src / "pack.csv", tmp_path / "s")
        report = verify_decision_ids(tmp_path / "s" / "pack.csv")
        assert report["ok"] is False
        assert report["mismatched"] == []
        assert any(p["code"] == "evidence-redacted" for p in report["problems"])


class TestTheBundleSaysHowToCheckIt:
    """A recipient who has never seen arche must still be able to verify.

    Shipping the instruction inside the folder is what makes "hand this to
    somebody who does not trust you" an instruction rather than a slogan: the
    command, what it proves, and what it does not.
    """

    def test_a_verifiable_bundle_names_the_command(self, tmp_path):
        from arche.review import share_artifact
        res = reconcile(_A, _B, entity="person", id_field="id")
        review_pack(res, _A, _B, out_dir=tmp_path / "w", entity="person")
        share_artifact(tmp_path / "w" / "pack.csv", tmp_path / "s")
        note = (tmp_path / "s" / "HOW_TO_VERIFY.txt").read_text(encoding="utf-8")
        assert "arche review verify-decisions" in note
        assert "pip install arche-core" in note
        # The limit is stated as plainly as the capability.
        assert "DOES NOT PROVE" in note
        # Whitespace-normalised: the note is hard-wrapped for a terminal, so
        # the phrase spans a line break.
        assert "needs the records" in " ".join(note.split())

    def test_an_unverifiable_bundle_says_so_instead(self, tmp_path):
        """It must not print a command that cannot work."""
        from arche.review import share_artifact
        src = tmp_path / "src"
        src.mkdir()
        with (src / "pack.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["decision_id", "decision", "score", "a_id",
                             "a_name", "b_id", "b_name", *REVIEW_FIELDS])
            writer.writerow(["xwd:sha256:beef", "match", "0.9", "p1", "Ada",
                             "p2", "Ada", *["" for _ in REVIEW_FIELDS]])
        share_artifact(src / "pack.csv", tmp_path / "s")
        note = (tmp_path / "s" / "HOW_TO_VERIFY.txt").read_text(encoding="utf-8")
        assert "CANNOT BE RECOMPUTED" in note
        assert "arche review verify-decisions" not in note
        assert "no pins" in note

    def test_the_note_carries_no_source_values(self, tmp_path):
        """It is part of the shared bundle and under the same promise."""
        from arche.review import share_artifact
        res = reconcile(_A, _B, entity="person", id_field="id")
        review_pack(res, _A, _B, out_dir=tmp_path / "w", entity="person")
        share_artifact(tmp_path / "w" / "pack.csv", tmp_path / "s")
        note = (tmp_path / "s" / "HOW_TO_VERIFY.txt").read_text(encoding="utf-8")
        for value in ("Amara", "Patel"):
            assert value not in note
