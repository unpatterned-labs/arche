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
import json
import re
import shutil
import subprocess
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
        # The layout as the module configures it, captured before any test
        # patches it. Two tests below assert on where the key and the database
        # really live, and a patched path would let them pass while the shipped
        # arrangement was wrong.
        module._real_layout = {"packs": module.PACKS,
                               "key": module.KEY_PATH,
                               "state": module.STATE.path}
        yield module
    finally:
        sys.path.remove(str(_STUDIO))


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, studio, monkeypatch):
    """Point every piece of studio state at a temporary directory.

    Not optional, and not only tidiness. `STATE` is a module-level `Store` bound
    to `data/_studio/state.sqlite3` at import, so a test that patched `PACKS` and
    nothing else appended its marks to the database a real reviewer is using.
    Fourteen rows keyed to this file's `p/pack.csv` fixture reached one before
    anybody noticed, which is a test suite quietly writing to production.

    Autouse, because remembering to ask for it is the thing that failed.
    """
    from state import Store
    monkeypatch.setattr(studio, "STATE", Store(tmp_path / "state.sqlite3"))
    monkeypatch.setattr(studio, "STUDIO_STATE", tmp_path)
    monkeypatch.setattr(studio, "KEY_PATH", tmp_path / "key.pem")
    monkeypatch.setattr(studio, "HASH_KEY_PATH", tmp_path / "hash.key")
    monkeypatch.setattr(studio, "PACKS", tmp_path)


@pytest.fixture
def pack(tmp_path, studio):
    """A real pack, written by the library, inside the studio's pack directory."""
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
        """Belt as well as braces: even if the id check were bypassed.

        Asserted against the real configured layout, not the test's temporary
        one, because the shipped arrangement is the thing that matters.
        """
        real = studio._real_layout
        assert not real["key"].resolve().is_relative_to(real["packs"].resolve())

    def test_the_state_database_is_not_either(self, studio):
        real = studio._real_layout
        assert not real["state"].resolve().is_relative_to(real["packs"].resolve())

    def test_a_file_with_no_reader_is_refused(self, studio, pack, tmp_path):
        """The extension set widened to the formats the library reads. A `.pem`
        is still not one of them."""
        (tmp_path / "secret.pem").write_text(
            "-----BEGIN PRIVATE KEY-----", encoding="utf-8")
        with pytest.raises(ValueError, match="a pack is a"):
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


class TestTheStudioReadsWhateverTheLibraryReads:
    """Pack parsing moved into `arche.review`, and the tool asks it.

    The studio used to run `csv.DictReader` itself and infer the two sides
    itself, so a parquet pack was simply unopenable and the row count was wrong
    for any quoted field holding a newline. Two implementations of "what is a
    pack" is one too many.
    """

    @staticmethod
    def _as_parquet(studio, tmp_path):
        """Rewrite the CSV fixture as parquet, with real numeric types."""
        pq = pytest.importorskip("pyarrow.parquet")
        import pyarrow as pa
        from arche.review import read_pack
        rows = []
        for row in read_pack(tmp_path / "p").rows:
            rec = dict(row)
            for k in ("score", "distinctive_max"):
                if rec.get(k) not in (None, ""):
                    rec[k] = float(rec[k])
            rows.append(rec)
        out = tmp_path / "q"
        out.mkdir()
        pq.write_table(pa.Table.from_pylist(rows), out / "pack.parquet")
        return "q/pack.parquet"

    def test_a_parquet_pack_opens(self, studio, pack, tmp_path):
        loaded = studio._load_pack(self._as_parquet(studio, tmp_path))
        assert len(loaded["rows"]) == 3
        assert loaded["format"] == "parquet"

    def test_it_is_listed_with_the_right_row_count(self, studio, pack, tmp_path):
        pid = self._as_parquet(studio, tmp_path)
        assert any(p["id"] == pid and p["rows"] == 3 for p in studio._packs())

    def test_and_digests_the_same_as_its_csv_twin(self, studio, pack, tmp_path):
        """The property that makes multi-format safe rather than merely possible.

        If a parquet pack and the identical CSV disagreed on the content digest,
        the same pack in two formats would fail each other's integrity check and
        an adjudication made against one would not verify against the other.
        """
        parquet = studio._load_pack(self._as_parquet(studio, tmp_path))
        assert parquet["content_digest"] == studio._load_pack(pack)["content_digest"]

    def test_a_mark_made_against_either_format_is_the_same_mark(
            self, studio, pack, tmp_path):
        """Because the digest agrees, so does the audit trail."""
        pid = self._as_parquet(studio, tmp_path)
        did = studio._load_pack(pid)["rows"][0]["decision_id"]
        studio._mark({"pack": pid, "decision_id": did,
                      "outcome": "same_entity", "reviewer": "dee"})
        stored = studio.STATE.current(pid)[did]
        assert stored["pack_digest"] == studio._load_pack(pack)["content_digest"]

    def test_the_sides_come_from_the_library(self, studio, pack):
        from arche.review import _infer_sides
        loaded = studio._load_pack(pack)
        assert loaded["sides"] == _infer_sides(loaded["fields"])


class TestWorkingTheQueueChangesSomething:
    """The reported defect: marking rows appeared to do nothing.

    Marks were persisting correctly the whole time — the store is append-only
    and the HTTP path was sound. What was missing was any consequence. The
    decision column still read `review`, the row stayed in the needs-a-human
    filter, and the queue was exactly as long after an hour's work as before it.
    A reviewer reasonably reads that as "it didn't save".
    """

    @pytest.fixture
    def held(self, tmp_path, studio):
        """A pack of pairs the gate refuses to merge: identical ordinary names.

        This is the queue a reviewer actually gets, and the `person` fixture
        above does not produce one because those pairs all match outright.
        """
        records = [{"id": f"r{i}", "name": n} for i, n in enumerate(
            ["General Hospital", "General Hospital", "Central Clinic",
             "Central Clinic", "Cottage Hospital"])]
        res = crosswalk(records, records, entity="place", id_field="id")
        review_pack(res, records, records, out_dir=tmp_path / "q",
                    entity="place", sides=("reg", "sur"), reveal=True)
        return "q/pack.csv"

    def test_the_fixture_really_does_hold_rows_for_a_human(self, studio, held):
        rows = studio._load_pack(held)["rows"]
        assert sum(1 for r in rows if r["decision"] == "review") >= 3

    def test_the_outstanding_count_falls_as_rows_are_settled(self, studio, held):
        """The number the reviewer cares about, and the one that did not exist."""
        rows = studio._load_pack(held)["rows"]
        queue = [r for r in rows if r["decision"] == "review"]
        seen = [studio._marks(held)["outstanding"]]
        for row in queue:
            studio._mark({"pack": held, "decision_id": row["decision_id"],
                          "outcome": "different", "reviewer": "dee"})
            seen.append(studio._marks(held)["outstanding"])
        assert seen == list(range(len(queue), -1, -1)), seen

    def test_cannot_tell_leaves_it_outstanding(self, studio, held):
        """It is a finding, not a resolution. The row stays in the queue."""
        row = next(r for r in studio._load_pack(held)["rows"]
                   if r["decision"] == "review")
        before = studio._marks(held)["outstanding"]
        studio._mark({"pack": held, "decision_id": row["decision_id"],
                      "outcome": "unresolved", "reviewer": "dee"})
        assert studio._marks(held)["outstanding"] == before

    def test_the_page_is_told_what_an_outcome_means(self, studio, held):
        """Served, not hard-coded in the page, so the two cannot drift."""
        from arche.review import OUTCOME_DECISION
        assert studio._load_pack(held)["outcome_decision"] == dict(OUTCOME_DECISION)

    def test_the_saved_copy_carries_the_merged_answer(self, studio, held,
                                                      tmp_path, monkeypatch):
        monkeypatch.setattr(studio, "REPO", tmp_path)
        row = next(r for r in studio._load_pack(held)["rows"]
                   if r["decision"] == "review")
        studio._mark({"pack": held, "decision_id": row["decision_id"],
                      "outcome": "same_entity", "reviewer": "dee"})
        studio._save_review({"pack": held, "reviewer": "dee"})
        import csv as _csv
        saved = {r["decision_id"]: r for r in _csv.DictReader(
            (tmp_path / "q" / "pack_reviewed.csv").open(encoding="utf-8"))}
        assert saved[row["decision_id"]]["decision"] == "review"
        assert saved[row["decision_id"]]["effective_decision"] == "match"

    def test_a_pack_outside_the_repo_still_saves(self, studio, held, tmp_path,
                                                 monkeypatch):
        """`relative_to` raises rather than falling back, so a pack directory
        outside the checkout turned a successful save into a subpath error."""
        monkeypatch.setattr(studio, "REPO", tmp_path.parent / "elsewhere")
        result = studio._save_review({"pack": held, "reviewer": "dee"})
        assert result["written"].endswith("pack_reviewed.csv")


def _has_gliner() -> bool:
    """The Documents tab needs a real NER backend to find a PERSON at all.

    `detect` falls back to regex-only without one, which finds the identifiers
    and none of the names — so the tests below would fail for a reason that has
    nothing to do with what they are testing. GliNER is an optional extra
    (`arche-core[detect]`), so this is a legitimate skip rather than a hidden
    dependency.
    """
    import importlib.util
    return importlib.util.find_spec("gliner") is not None


needs_ner = pytest.mark.skipif(
    not _has_gliner(),
    reason="needs a NER backend: pip install arche-core[detect]")


@needs_ner
class TestReadingSeveralDocumentsAtOnce:
    """The Documents tab: extract, hide, and link across files.

    The claim this tab makes is that what you can see has been decided about,
    and the claim is only worth as much as the leak tests below. A masked view
    that leaves the name in the body text while hiding it in the entity list is
    worse than showing everything, because it earns a trust it has not got —
    and that is exactly what the first implementation did, because the NG
    policy emits no rule at all for a PERSON and `redacted_text` therefore left
    it in place.
    """

    A = ("Referral note. Dr Adesola Okonkwo, NIN 12345678901, reviewed the "
         "patient at Karfi Health Post in Kano on 2 March. Reach the clinic on "
         "08031234567 or adesola@example.ng.")
    B = ("Staff register, Kano State. Adesola Okonkwo is listed at Karfi "
         "Primary Health Centre. Contact 0803 123 4567. Malik Bello covers "
         "the Wudil ward.")

    @pytest.fixture
    def masked(self, studio):
        return studio._documents({"documents": [
            {"name": "referral.txt", "text": self.A},
            {"name": "register.txt", "text": self.B}], "jurisdiction": "NG"})

    @pytest.fixture
    def revealed(self, studio):
        return studio._documents({"documents": [
            {"name": "referral.txt", "text": self.A},
            {"name": "register.txt", "text": self.B}],
            "jurisdiction": "NG", "reveal": True})

    def test_both_documents_come_back(self, masked):
        assert [d["name"] for d in masked["documents"]] == ["referral.txt",
                                                            "register.txt"]

    def test_entities_are_found(self, masked):
        assert masked["counts"]["PERSON"] >= 2
        assert masked["counts"]["NATIONAL_ID"] >= 1

    def test_nothing_identifying_survives_anywhere_in_the_response(self, masked):
        """The whole response, serialised: entity list, body text, links,
        manifest. A leak in any one of them is a leak."""
        blob = json.dumps(masked)
        for secret in ("Adesola Okonkwo", "12345678901", "08031234567",
                       "adesola@example.ng", "Malik Bello"):
            assert secret not in blob, f"{secret!r} survived masking"

    def test_the_body_text_is_masked_too_not_just_the_list(self, masked):
        """The specific defect. `redacted_text` does not hide a PERSON under
        NDPA, so the tab must hide the spans it decided to hide itself."""
        for doc in masked["documents"]:
            assert "Adesola" not in doc["text"]
            assert "[PERSON]" in doc["text"]

    def test_a_name_is_hidden_with_no_statute_behind_it_and_says_so(self, masked):
        """Uncovered is not permission. A name draws no NDPA rule, and hiding it
        anyway has to be labelled as this tab's choice, not a statute's.

        The action label distinguishes two cases that used to share the word
        `uncovered`. See `TestTheTwoDetectorsAreNotConflated` below for why.
        """
        person = next(e for e in masked["documents"][0]["entities"]
                      if e["type"] == "PERSON")
        assert person["masked"] is True
        assert person["action"] in {"uncovered", "not evaluated"}
        assert person["authority"] == ""
        # Both labels must carry this, and the wording is the assertion. A
        # first pass at the `not evaluated` rationale dropped the phrase, which
        # this test caught: without it a reader can conclude a statute is what
        # hid the name, which is the exact inference the tab must not invite.
        assert "not because a statute" in person["rationale"]

    def test_a_removal_carries_its_citation(self, masked):
        nin = next(e for e in masked["documents"][0]["entities"]
                   if e["type"] == "NATIONAL_ID")
        assert nin["masked"] is True
        assert "NDPA" in nin["authority"]

    def test_retain_is_a_decision_and_stays_visible(self, masked):
        """A statute permitting you to keep something is doing as much work as
        one telling you to drop it."""
        kano = next(e for e in masked["documents"][0]["entities"]
                    if e["type"] == "LOCATION" and e["action"] == "retain")
        assert kano["masked"] is False
        assert kano["shown"] == "Kano"

    def test_revealing_returns_the_values(self, revealed):
        assert "Adesola Okonkwo" in json.dumps(revealed)
        assert revealed["revealed"] is True

    def test_the_masked_response_never_carried_them_at_all(self, masked):
        """`raw` is stripped at the boundary. If it survived, "redacted" would
        be a statement about CSS rather than about the data."""
        for doc in masked["documents"]:
            assert all("raw" not in e for e in doc["entities"])


@needs_ner
class TestLinkingAcrossDocuments:
    """Why the tab takes more than one file.

    One document tells you a person is mentioned. Two and a matcher tell you
    whether it is the same person, which is the question anybody reconciling a
    register against a survey actually has.
    """

    A = TestReadingSeveralDocumentsAtOnce.A
    B = TestReadingSeveralDocumentsAtOnce.B

    @pytest.fixture
    def masked(self, studio):
        return studio._documents({"documents": [
            {"name": "a.txt", "text": self.A},
            {"name": "b.txt", "text": self.B}], "jurisdiction": "NG"})

    def test_one_document_produces_no_links(self, studio):
        one = studio._documents({"documents": [{"name": "a.txt", "text": self.A}]})
        assert one["links"] == []

    def test_the_two_mentions_of_the_person_are_paired(self, masked):
        assert any(link["type"] == "PERSON" for link in masked["links"])

    def test_the_pair_is_judged_though_the_page_cannot_see_the_names(self, masked):
        """The point of running the matcher on real values and masking only the
        display: you read the judgement without reading the name.

        Feeding the matcher `[PERSON]` against `[PERSON]` would score the
        placeholder — every masked mention of a type is byte-identical to every
        other — and the answer would be about nothing.
        """
        person = next(k for k in masked["links"] if k["type"] == "PERSON")
        assert person["a"] == "[PERSON]" and person["b"] == "[PERSON]"
        assert 0.0 < person["score"] < 1.0
        assert person["decision"] in {"match", "review", "no_match"}

    def test_the_score_is_the_same_whether_or_not_you_revealed(self, studio,
                                                              masked):
        """Masking is a display control. It must not move the answer."""
        revealed = studio._documents({"documents": [
            {"name": "a.txt", "text": self.A},
            {"name": "b.txt", "text": self.B}],
            "jurisdiction": "NG", "reveal": True})
        before = {(k["a_id"], k["b_id"]): k["score"] for k in masked["links"]}
        after = {(k["a_id"], k["b_id"]): k["score"] for k in revealed["links"]}
        assert before == after

    def test_an_entity_id_does_not_hash_the_value(self, masked):
        """An id over the text would be a way to confirm a guess at what was
        hidden. It is over position and type instead."""
        import hashlib
        person = next(e for e in masked["documents"][0]["entities"]
                      if e["type"] == "PERSON")
        assert person["id"] != hashlib.sha256(
            b"Dr Adesola Okonkwo").hexdigest()[:16]


class TestDocumentRefusals:

    def test_nothing_attached_is_refused(self, studio):
        with pytest.raises(ValueError, match="at least one document"):
            studio._documents({"documents": []})

    def test_an_empty_document_is_named(self, studio):
        with pytest.raises(ValueError, match="empty.txt has no readable text"):
            studio._documents({"documents": [{"name": "empty.txt", "text": "  "}]})

    def test_a_batch_is_refused(self, studio):
        """A reading tool, not a pipeline."""
        with pytest.raises(ValueError, match="eight documents"):
            studio._documents({"documents": [
                {"name": f"{i}.txt", "text": "x"} for i in range(9)]})


class TestThePageHangsTogether:
    """Structural checks on `index.html`, which nothing else can reach.

    The interface is one file of hand-written HTML and JavaScript with no build
    step, so there is no compiler to notice that a handler was bound to an id
    that does not exist, or that a tab was added to the switcher without a
    section to switch to. Those fail silently in a browser — a dead button, a
    blank panel — and the last time something in this file failed silently it
    was a `NameError` that emptied the review queue while every test stayed
    green.

    These are cheap and catch that whole class. They are not a substitute for
    opening the page.
    """

    @pytest.fixture(scope="class")
    def page(self):
        return (_STUDIO / "index.html").read_text(encoding="utf-8")

    @staticmethod
    def _ids(page):
        return set(re.findall(r'id="([^"]+)"', page))

    def test_every_element_the_script_reaches_for_exists(self, page):
        wanted = set(re.findall(r'\$\("#([a-zA-Z0-9_-]+)"\)', page))
        wanted |= set(re.findall(r'on\("([a-zA-Z0-9_-]+)"', page))
        assert not (wanted - self._ids(page))

    def test_every_tab_has_both_a_button_and_a_section(self, page):
        names = re.search(r"const tab=t=>\{for\(const k of\[([^\]]+)\]",
                          page).group(1)
        names = [n.strip().strip('"') for n in names.split(",")]
        ids = self._ids(page)
        assert len(names) >= 6
        for name in names:
            assert f"t-{name}" in ids, f"{name} has no nav button"
            assert f"s-{name}" in ids, f"{name} has no section"

    def test_every_nav_button_is_in_the_switcher(self, page):
        """The reverse direction: a button that switches to nothing."""
        names = re.search(r"const tab=t=>\{for\(const k of\[([^\]]+)\]",
                          page).group(1)
        names = {n.strip().strip('"') for n in names.split(",")}
        buttons = {i[2:] for i in self._ids(page) if i.startswith("t-")}
        assert buttons == names

    def test_the_outcome_buttons_use_the_library_vocabulary(self, page):
        """A button posting an outcome the store will reject is a dead button."""
        from arche.report import REVIEW_OUTCOMES
        for outcome in REVIEW_OUTCOMES:
            assert f'mark("{outcome}")' in page, outcome

    def test_the_accent_is_only_ever_a_mark(self, page):
        """THE RULE in DESIGN.md: `#A33B1F` is a mark, never running copy.

        Borders are always marks, so the check is on `color:` alone, and on the
        *selector* rather than the line — a CSS rule spans lines and a
        declaration does not carry its own selector with it.

        This cannot tell a mark from prose by itself; that is a judgement. What
        it can do is pin the set, so a seventh accent-coloured thing fails here
        and has to be argued for rather than drifting in. The allowlist is the
        uses DESIGN.md names, plus two controls that are labels rather than copy.
        """
        blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", page)
        coloured = {
            " ".join(selector.split())
            for selector, body in blocks
            if re.search(r"(?<![-\w])color:\s*var\(--accent\)", body)
        }
        allowed = {
            ".alpha",                        # the version badge
            "nav button[aria-current=true]",  # 1. where you are
            "mark sup",                      # 3. the mark on a place mention
            "table.grid th .sort",           # 7. which column is sorted
            ".drop:hover",                   # a control, not copy
        }
        assert coloured <= allowed, coloured - allowed

    def test_and_the_documented_marks_are_actually_there(self, page):
        """The reverse: THE RULE describes marks the page is supposed to carry.

        A rule nothing implements has stopped being a design system and become
        a wish.
        """
        flat = " ".join(page.split())
        assert "nav button[aria-current=true]" in flat
        assert "input:focus,select:focus,textarea:focus" in flat

    def test_the_script_parses(self, page, tmp_path):
        """The whole interface is one inline script with no build step.

        A syntax error anywhere in it kills the entire file: no listeners are
        registered, every tab and button is inert, and the page looks frozen
        rather than broken. That is exactly what shipped — a `title=` attribute
        written with apostrophes inside a single-quoted JavaScript string
        terminated the string early, and the studio came up dead.

        The structural checks above all passed against that page, because every
        id it referenced did exist. They were checking the wrong layer. Nothing
        substitutes for handing the script to something that can parse it.
        """
        node = shutil.which("node")
        if not node:
            pytest.skip("needs node to parse the script")
        script = re.search(r"<script>(.*?)</script>", page, re.S)
        assert script, "index.html has no inline script"
        path = tmp_path / "studio.js"
        path.write_text(script.group(1), encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr

    def test_every_function_called_at_load_is_defined(self, page):
        """A syntax check does not catch a call to a name that does not exist.

        The load sequence runs several functions in a row, so the first one that
        throws takes the rest of the startup with it — the same dead page from a
        different cause.
        """
        defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", page))
        defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
                                  page))
        boot = re.search(r"\(async\(\)=>\{(.*?)\}\)\(\);", page, re.S)
        assert boot, "the load sequence is not where this test expects it"
        # Bare calls only. A method call carries its receiver, so `x.foo()` is
        # not a claim that `foo` is a top-level function.
        called = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\(",
                                boot.group(1)))
        missing = {c for c in called
                   if c not in defined
                   and c not in {"fetch", "await", "if", "for", "while",
                                 "return", "typeof", "catch", "Error"}}
        assert not missing, missing

    def test_the_page_boots_without_throwing(self, page):
        """Parsing is not running.

        A script can parse perfectly and still throw on the first line of its
        startup — a call to something undefined, a `const` read inside its
        temporal dead zone — and the result on screen is the same inert page.
        `studio_boot.mjs` runs the real script against a stub DOM and stub
        endpoints, exercises every tab switch, and fails on anything thrown.
        """
        node = shutil.which("node")
        if not node:
            pytest.skip("needs node to run the script")
        harness = Path(__file__).with_name("studio_boot.mjs")
        done = subprocess.run(
            [node, str(harness), str(_STUDIO / "index.html")],
            capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stdout + done.stderr


class TestTheChatTabDegradesHonestly:
    """arche studio gained an agent chat, and with it a first dependency it
    cannot guarantee.

    Everything else in the tool runs on the standard library plus arche-core.
    The chat needs `openai`, an API key, and an importable `arche-mcp`, and any
    of the three can be absent on a machine where the rest works perfectly.

    So the tab always renders and says which one is missing. A single "chat
    unavailable" would send somebody looking in the wrong place — a missing
    package, a missing key and a missing workspace member need three different
    fixes.

    These tests never call a model. They cover the readiness contract and the
    refusal, which are the parts that must hold on a machine with no key.
    """

    def test_readiness_names_each_missing_thing(self, studio, monkeypatch):
        monkeypatch.setattr(studio, "_openai_key", lambda: "")
        ready = studio._chat_ready()
        assert ready["ready"] is False
        assert any("OPENAI_API_KEY" in m for m in ready["missing"])

    def test_it_reports_the_model_either_way(self, studio, monkeypatch):
        """So the tab can show what it would use before it can use it."""
        monkeypatch.setattr(studio, "_openai_key", lambda: "")
        assert studio._chat_ready()["model"]

    def test_a_turn_refuses_rather_than_erroring_obscurely(self, studio, monkeypatch):
        monkeypatch.setattr(studio, "_openai_key", lambda: "")
        with pytest.raises(ValueError, match="chat is not available"):
            studio._chat({"messages": [{"role": "user", "content": "hi"}]})

    def test_the_refusal_says_what_to_do(self, studio, monkeypatch):
        monkeypatch.setattr(studio, "_openai_key", lambda: "")
        try:
            studio._chat({"messages": [{"role": "user", "content": "hi"}]})
        except ValueError as exc:
            assert "OPENAI_API_KEY" in str(exc)

    def test_an_empty_conversation_is_refused(self, studio, monkeypatch):
        monkeypatch.setattr(studio, "_openai_key", lambda: "k")
        with pytest.raises(ValueError, match="at least one message"):
            studio._chat({"messages": []})

    def test_the_key_is_never_returned_to_the_page(self, studio):
        """`_chat_ready` is a GET the browser calls on every tab switch."""
        import json as _json
        assert "sk-" not in _json.dumps(studio._chat_ready())


class TestTheChatUsesTheRealToolSurface:
    """The point of threading MCP through rather than reimplementing.

    Schemas come from `arche_mcp.server.mcp.list_tools()` and dispatch goes
    through `mcp.call_tool()`, so the descriptions, the enums and the results
    are the ones a real client sees. What is skipped is the JSON-RPC framing.

    If this ever drifts into a private copy of the tool list, the studio starts
    demonstrating something that is not what ships.
    """

    def test_dispatch_goes_through_the_mcp_server(self, studio):
        import inspect
        source = inspect.getsource(studio._chat)
        assert "_mcp.call_tool" in source
        assert "_mcp.list_tools" in source

    def test_the_server_dispatches_in_process(self):
        """The mechanism the tab depends on."""
        import asyncio

        from arche_mcp.server import mcp
        result = asyncio.run(mcp.call_tool(
            "infer_jurisdiction", {"text": "NIN 12345678901, RC 1234567"}))
        text = "".join(c.text for c in result.content if getattr(c, "text", None))
        assert '"country": "NG"' in text

    def test_the_tool_count_matches_the_published_server(self):
        """A literal, and deliberately so.

        The studio is a consumer of the MCP surface, not its owner. Adding a
        tool in `arche-mcp` should make somebody confirm the consumer still
        renders it, and a hard number is the cheapest way to force that
        acknowledgement. `arche-mcp` has its own inventory test naming every
        tool; this one only asks whether the count moved under the studio's
        feet.

        Went 10 -> 11 when `why_unresolved` was added.
        """
        import asyncio

        from arche_mcp.server import mcp
        assert len(asyncio.run(mcp.list_tools())) == 11

    def test_the_step_cap_is_bounded(self, studio):
        """A model stuck in a retry loop should cost seconds, not a bill."""
        assert 1 < studio._CHAT_MAX_STEPS <= 12


def test_the_chat_tab_is_registered_in_the_page(studio):
    """Same structural contract as every other tab."""
    page = (_STUDIO / "index.html").read_text(encoding="utf-8")
    assert 'id="t-chat"' in page and 'id="s-chat"' in page
    names = re.search(r"const tab=t=>\{for\(const k of\[([^\]]+)\]", page).group(1)
    assert '"chat"' in names


def test_the_marketplace_threat_case_keeps_each_claim_narrow(studio):
    """A product edge cannot silently become an enforcement conclusion."""
    case = studio._threat_case()
    decisions = {row["id"]: row["product_decision"]["decision"]
                 for row in case["observations"]}

    assert case["synthetic"] is True
    assert decisions == {
        "market-a-104": "match",
        "market-b-77": "review",
        "market-c-18": "not_linked",
    }
    assert "infringement" in case["relationships"][-1]["limit"].lower()
