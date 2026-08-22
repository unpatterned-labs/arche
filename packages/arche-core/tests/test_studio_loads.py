# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The studio can still open a pack the library just wrote.

This exists because it did not. A line-based edit to `_load_pack` deleted the
line defining `ids`, every pack raised `NameError` on load, and the review queue
came up empty. The library tests were green throughout, because nothing anywhere
imported the studio.

That is the gap this closes. The studio is not shipped in the wheel and is not
covered by its own tests, so the one thing worth asserting from here is the
contract between them: `review_pack` writes it, `_load_pack` reads it, and a
change to either that breaks the other should fail a test rather than a user.

Deliberately a smoke test. It is not a substitute for testing the studio, and
anything about the HTTP surface, the SQLite store or the UI belongs elsewhere.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from arche.report import review_pack
from arche.resolve import crosswalk

_STUDIO = Path(__file__).resolve().parents[3] / "tools" / "arche-studio"

pytestmark = pytest.mark.skipif(
    not (_STUDIO / "serve.py").exists(),
    reason="arche-studio is not present in this checkout",
)

_A = [{"id": str(i), "name": n, "birth_date": d}
      for i, (n, d) in enumerate(
          [("Amara Patel", "2016-06-28"),
           ("Malik Okonkwo", "2017-08-18"),
           ("Ngozi Adeyemi", "1990-03-02")])]


@pytest.fixture(scope="module")
def studio():
    """Import serve.py without installing it. It imports `state` as a sibling."""
    sys.path.insert(0, str(_STUDIO))
    try:
        spec = importlib.util.spec_from_file_location(
            "arche_studio_serve", _STUDIO / "serve.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(_STUDIO))


@pytest.fixture
def pack(tmp_path, studio, monkeypatch):
    """A real pack, written by the library, inside the studio's pack directory."""
    monkeypatch.setattr(studio, "PACKS", tmp_path)
    res = crosswalk(_A, _A, entity="person", id_field="id")
    review_pack(res, _A, _A, out_dir=tmp_path / "p", entity="person",
                sides=("left", "right"), reveal=True)
    return "p/pack.csv"


def test_the_studio_can_load_a_pack_the_library_wrote(studio, pack):
    """The regression. This raised NameError and emptied the review queue."""
    loaded = studio._load_pack(pack)
    assert len(loaded["rows"]) == 3


def test_it_finds_the_pack_in_the_listing(studio, pack):
    listed = studio._packs()
    assert any(p["id"] == pack and p["rows"] == 3 for p in listed)


def test_the_two_sides_are_inferred_from_the_column_prefixes(studio, pack):
    """How the queue renders both records without being configured."""
    assert set(studio._load_pack(pack)["sides"]) == {"left", "right"}


def test_both_digests_are_present(studio, pack):
    """`content_digest` was the change that broke this. Assert it is there."""
    loaded = studio._load_pack(pack)
    assert len(loaded["content_digest"]) == 64
    assert len(loaded["digest"]) == 16


def test_the_content_digest_agrees_with_the_manifest(studio, pack):
    """The studio and the library must compute the same digest.

    Two implementations of one digest is how a pack starts failing its own
    integrity check for no reason.
    """
    loaded = studio._load_pack(pack)
    assert loaded["content_digest"] == loaded["manifest"]["content_sha256"]


def test_the_outcome_vocabulary_matches_the_library(studio):
    from arche.report import REVIEW_OUTCOMES
    assert tuple(studio._load_pack.__globals__["OUTCOMES"]) == tuple(REVIEW_OUTCOMES)


def test_a_pack_outside_the_pack_directory_is_refused(studio, pack):
    """Path traversal. The loader resolves and checks containment."""
    with pytest.raises(ValueError, match="escapes"):
        studio._load_pack("../../../etc/passwd")

class TestWhatThePackEndpointWillOpen:
    """`/api/pack?id=...` reads a file and parses it as CSV. What files?

    The check this replaced compared resolved paths with `str.startswith` and
    accepted any extension, so `_load_pack("_studio_key.pem")` returned the
    signing key's PEM lines as two CSV rows, and a sibling directory named
    `review_packs_evil` passed containment.
    """

    def test_the_signing_key_is_not_under_the_served_directory(self, studio):
        """Belt as well as braces: even if the id check were bypassed."""
        assert not studio.KEY_PATH.resolve().is_relative_to(studio.PACKS.resolve())

    def test_the_state_database_is_not_either(self, studio):
        assert not studio.STATE.path.resolve().is_relative_to(studio.PACKS.resolve())

    def test_a_non_csv_inside_the_directory_is_refused(self, studio, pack, tmp_path):
        (tmp_path / "secret.pem").write_text(
            "-----BEGIN PRIVATE KEY-----", encoding="utf-8")
        with pytest.raises(ValueError, match="a pack is a .csv file"):
            studio._load_pack("secret.pem")

    def test_traversal_is_refused(self, studio, pack):
        with pytest.raises(ValueError, match="escapes"):
            studio._load_pack("../../../pyproject.toml")

    def test_a_csv_that_was_never_offered_is_refused(self, studio, pack, tmp_path):
        """The id has to be one `_packs()` listed, not one the client invented."""
        sneaky = tmp_path / "p" / "notes_reviewed.csv"
        sneaky.write_text("a,b" + chr(10) + "1,2" + chr(10),
                          encoding="utf-8")
        with pytest.raises(ValueError, match="not one of the packs"):
            studio._load_pack("p/notes_reviewed.csv")


class TestMarkIdentityIsServerSide:
    """A mark is about a decision in a pack, and the server decides which.

    All three of `pack`, `pack_digest` and `decision_id` used to be taken from
    the request and believed, so a mark could be recorded against a decision the
    pack does not contain, under a digest that does not describe it, and
    `sign_pack` would then sign it.
    """

    def test_a_decision_not_in_the_pack_is_refused(self, studio, pack):
        with pytest.raises(ValueError, match="is not in"):
            studio._mark({"pack": pack, "decision_id": "invented",
                          "outcome": "same_entity", "reviewer": "someone"})

    def test_the_client_supplied_digest_is_ignored(self, studio, pack):
        loaded = studio._load_pack(pack)
        decision_id = loaded["rows"][0]["decision_id"]
        studio._mark({"pack": pack, "decision_id": decision_id,
                      "outcome": "unresolved", "reviewer": "dee",
                      "pack_digest": "a-lie-the-client-told"})
        stored = studio.STATE.current(pack)[decision_id]
        assert stored["pack_digest"] == loaded["content_digest"]


class TestAdjudicationVerification:
    """`verify_adjudication` used to ignore the signature entirely."""

    @staticmethod
    def _signed(tmp_path):
        import keyring
        keypair = keyring.load_or_create(tmp_path / "k.pem")
        marks = {"d1": {"outcome": "same_entity", "reviewer": "dee",
                        "reason": "", "marked_at": "t"},
                 "d2": {"outcome": "different", "reviewer": "dee",
                        "reason": "", "marked_at": "t"}}
        return keyring, keyring.sign_adjudication(
            keypair, pack="p", content_digest="c", rows=2, marks=marks)

    def test_an_honest_artifact_verifies(self, studio, tmp_path):
        keyring, signed = self._signed(tmp_path)
        report = keyring.verify_adjudication(signed)
        assert report["ok"] and report["signature_valid"]

    def test_valid_is_not_trusted_without_a_pinned_key(self, studio, tmp_path):
        """Integrity is not attribution, here as everywhere else in arche."""
        keyring, signed = self._signed(tmp_path)
        assert keyring.verify_adjudication(signed)["trusted"] is False

    def test_swapping_the_ledger_and_its_claimed_digest_is_caught(self, studio,
                                                                  tmp_path):
        """The exact attack the old function returned `outcomes_match=True` for."""
        import copy
        keyring, signed = self._signed(tmp_path)
        tampered = copy.deepcopy(signed)
        tampered["ledger"][0]["outcome"] = "different"
        tampered["manifest"]["outcomes_sha256"] = keyring._ledger_digest(
            tampered["ledger"])
        report = keyring.verify_adjudication(tampered)
        assert report["ok"] is False
        assert report["outcomes_match"] is False

    def test_an_unsigned_artifact_is_refused(self, studio, tmp_path):
        keyring, signed = self._signed(tmp_path)
        signed["jws"] = None
        assert keyring.verify_adjudication(signed)["ok"] is False


class TestSavingProducesBothArtifacts:
    """A save used to produce one file, revealed, and that was the file people
    sent each other.

    The reviewer's document has to carry real names — a masked pack cannot be
    adjudicated. So the fix is not to mask that one, it is to always write the
    other one beside it, because a redaction step you have to remember is a
    redaction step that does not happen.
    """

    @staticmethod
    def _save(studio, pack, tmp_path, monkeypatch):
        monkeypatch.setattr(studio, "REPO", tmp_path)
        loaded = studio._load_pack(pack)
        did = loaded["rows"][0]["decision_id"]
        studio._mark({"pack": pack, "decision_id": did,
                      "outcome": "same_entity", "reviewer": "dee",
                      "reason": "same person, Amara Patel, confirmed"})
        return studio._save_review({"pack": pack, "reviewer": "dee"})

    def test_both_are_written(self, studio, pack, tmp_path, monkeypatch):
        result = self._save(studio, pack, tmp_path, monkeypatch)
        assert result["written"].endswith("_reviewed.csv")
        assert result["shared"].endswith("_shared/pack.csv")
        assert result["warning"] is None

    def test_the_working_copy_still_carries_the_names(self, studio, pack,
                                                      tmp_path, monkeypatch):
        """The premise. Masking both would make the review unrepeatable."""
        self._save(studio, pack, tmp_path, monkeypatch)
        written = (tmp_path / "p" / "pack_reviewed.csv").read_text(encoding="utf-8")
        assert "Amara Patel" in written

    def test_and_the_shared_one_does_not(self, studio, pack, tmp_path,
                                         monkeypatch):
        self._save(studio, pack, tmp_path, monkeypatch)
        shared = tmp_path / "p" / "pack_shared"
        both = ((shared / "pack.csv").read_text(encoding="utf-8")
                + (shared / "manifest.json").read_text(encoding="utf-8"))
        assert "Amara Patel" not in both
        assert "[NAME]" in both

    def test_the_reason_does_not_survive_either(self, studio, pack, tmp_path,
                                                monkeypatch):
        """It names the person. Free text is masked by dropping it, not by
        running a detector over it that fails quietly."""
        self._save(studio, pack, tmp_path, monkeypatch)
        shared = (tmp_path / "p" / "pack_shared" / "pack.csv").read_text(
            encoding="utf-8")
        assert "confirmed" not in shared
        assert "same_entity" in shared, "the outcome itself must survive"

    def test_the_shared_copy_is_not_offered_as_a_pack(self, studio, pack,
                                                     tmp_path, monkeypatch):
        """It cannot be adjudicated, so it does not belong in the picker."""
        self._save(studio, pack, tmp_path, monkeypatch)
        assert not any(p["id"].endswith("_shared/pack.csv")
                       for p in studio._packs())
