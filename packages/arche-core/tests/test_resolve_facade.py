# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Step 3 (engine reconciliation): the resolve facade + coref_from_pipeline.

* resolve.compare dispatches on shape (Results / References / strings).
* coref_from_pipeline: jurisdiction contract (agree -> use; disagree -> require
  explicit), provenance (source jurisdictions + doc hashes) inside the hashed
  pins, restricted values flowing through.
* resolve.reconcile: entity packs as canned comparator specs; self-calibrated tf.
"""

import pytest
from arche import resolve
from arche.canonical import Reference
from arche.resolve.coreference import coref_from_pipeline
from arche.workflow._primitive import Pipeline

_KEY = b"facade-test-issuer-key-32-bytes!"


def _result(text, jurisdiction="NG"):
    return Pipeline(jurisdiction=jurisdiction, detectors=None).process(text)


# ── coref_from_pipeline ──────────────────────────────────────────────────────


def test_pipeline_results_resolve_end_to_end():
    a = _result("Fatima Abdullahi, NIN 12345678901, phone 08031234567.")
    b = _result("Patient Fatima Abdulahi (NIN 12345678901).")
    d = coref_from_pipeline(a, b, issuer_key=_KEY)
    assert d.identity == "same_entity"
    assert d.jurisdiction == "NG"                      # inherited from the results
    prov = d.pins["provenance"]
    assert prov["source_jurisdictions"] == ["NG", "NG"]
    assert prov["document_hash_a"] == a.document_hash  # inside the hashed pins
    assert prov["path"] == "pipeline"


def test_jurisdiction_disagreement_fails_loudly():
    a = _result("Fatima Abdullahi, NIN 12345678901.", jurisdiction="NG")
    b = _result("Fatima Abdullahi, phone +49 30 901820.", jurisdiction="DE")
    with pytest.raises(ValueError, match="different jurisdictions"):
        coref_from_pipeline(a, b)
    # Explicit jurisdiction resolves the disagreement.
    d = coref_from_pipeline(a, b, jurisdiction="NG", issuer_key=_KEY)
    assert d.jurisdiction == "NG"
    assert d.pins["provenance"]["source_jurisdictions"] == ["NG", "DE"]


def test_provenance_is_inside_the_decision_hash():
    a1 = _result("Fatima Abdullahi, NIN 12345678901.")
    b1 = _result("Fatima Abdulahi, NIN 12345678901.")
    d1 = coref_from_pipeline(a1, b1, issuer_key=_KEY)
    # Same references, DIFFERENT source document for b -> different decision_id
    # (the provenance claim is attested, i.e. under the hash).
    b2 = _result("Fatima Abdulahi,  NIN 12345678901.")  # extra space -> new doc hash
    d2 = coref_from_pipeline(a1, b2, issuer_key=_KEY)
    assert b1.document_hash != b2.document_hash
    assert d1.decision_id != d2.decision_id


# ── the facade: pairwise ─────────────────────────────────────────────────────


def test_pairwise_dispatches_on_shape():
    a = _result("Fatima Abdullahi, NIN 12345678901.")
    b = _result("Fatima Abdulahi, NIN 12345678901.")
    d = resolve.compare(a, b, issuer_key=_KEY)               # Results
    assert d.identity == "same_entity"

    ra = Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "N1"})
    rb = Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "N1"})
    d2 = resolve.compare(ra, rb, jurisdiction="NG", issuer_key=_KEY)  # References
    assert d2.identity == "same_entity"

    # Matches on the shapes rather than the function name: `pairwise`
    # forwards to `compare`, and either spelling must refuse a mixed pair.
    with pytest.raises(TypeError, match="expects two dicts"):
        resolve.compare(ra, "a string")                      # mixed shapes


def test_compare_covers_every_shipped_pack():
    # This assertion used to read `raises(NotImplementedError, match="person
    # only")`. That was the honest guard for a facade that answered the
    # pairwise question for people and told everyone else to go and build a
    # two-item list. The pack engine answers it for every pack, so the guard
    # now records the capability instead of the restriction.
    a = {"name": "Karfi Primary Health Centre", "lat": 11.6, "lon": 8.4}
    b = {"name": "Karfi PHC", "lat": 11.6005, "lon": 8.4005}
    decision = resolve.compare(a, b, entity="place")
    assert decision.identity in {"same_entity", "review", "different"}
    assert decision.pins["entity_pack"] == "place"


def test_compare_refuses_a_pack_it_does_not_ship():
    # Loudly, and by naming what it does have. A typo'd pack silently falling
    # back to `person` would score a clinic against a person schema.
    with pytest.raises(ValueError, match="no entity pack named"):
        resolve.compare({"name": "x"}, {"name": "y"}, entity="hospitl")


def test_compare_refuses_strings_for_a_pack_entity():
    # The pack engine scores declared fields. Handed two strings it has no
    # fields to score, and guessing which one is the name is how a matcher
    # starts quietly inventing schema.
    with pytest.raises(TypeError, match="expects two dict records"):
        resolve.compare("a", "b", entity="place")


# ── the facade: crosswalk + entity packs ─────────────────────────────────────

_FACILITIES_A = [
    {"id": "A1", "name": "Karfi Primary Health Centre", "lat": 11.6, "lon": 8.4},
    {"id": "A2", "name": "Central Hospital Kano", "lat": 12.0, "lon": 8.5},
]
_FACILITIES_B = [
    {"id": "B1", "name": "Karfi PHC", "lat": 11.6005, "lon": 8.4005},
    {"id": "B2", "name": "Gwale Clinic", "lat": 12.1, "lon": 8.6},
]


def test_crosswalk_place_pack_links_facilities():
    out = resolve.reconcile(_FACILITIES_A, _FACILITIES_B, entity="place")
    pairs = {(m["a_id"], m["b_id"]): m for m in out["matches"]}
    assert ("A1", "B1") in pairs          # Karfi PHC surfaced
    assert out["blocking"]["candidate_pairs"] <= 4


def test_crosswalk_contract_returns_candidate_edges_not_non_matches():
    out = resolve.reconcile(_FACILITIES_A, _FACILITIES_B, entity="place", block=None)
    assert {edge["decision"] for edge in out["matches"]} <= {"match", "review"}
    assert all({"a_id", "b_id", "score", "evidence", "decision_id"} <= edge.keys()
               for edge in out["matches"])
    assert ("A2", "B2") not in {(edge["a_id"], edge["b_id"]) for edge in out["matches"]}


def test_crosswalk_requires_pack_or_comparators():
    with pytest.raises(ValueError, match="entity="):
        resolve.reconcile(_FACILITIES_A, _FACILITIES_B)
    with pytest.raises(ValueError, match="unknown entity pack"):
        resolve.reconcile(_FACILITIES_A, _FACILITIES_B, entity="starship")


def test_crosswalk_person_pack_runs():
    people_a = [{"id": "P1", "name": "Ngozi Okonkwo", "phone": "08031234567"}]
    people_b = [{"id": "P2", "name": "Ngozi Okonkwo", "phone": "0803 123 4567"}]
    out = resolve.reconcile(people_a, people_b, entity="person", block=None)
    assert out["matches"] and out["matches"][0]["decision"] in ("match", "review")


def test_pairwise_contract_keeps_identity_and_action_separate():
    same = resolve.compare(
        Reference.from_record({"full_name": "Fatima Abdullahi", "national_id": "12345678901"}),
        Reference.from_record({"full_name": "Fatima Abdullahi", "national_id": "12345678901"}),
        jurisdiction="NG",
    )
    different = resolve.compare(
        Reference.from_record({"full_name": "Fatima Abdullahi", "national_id": "12345678901"}),
        Reference.from_record({"full_name": "Fatima Abdullahi", "national_id": "10987654321"}),
        jurisdiction="NG",
    )
    assert (same.identity, same.action) == ("same_entity", "merge")
    assert (different.identity, different.action) == ("different", "no_op")


def test_explicit_comparators_override_pack():
    out = resolve.reconcile(
        _FACILITIES_A, _FACILITIES_B,
        comparators=[{"field": "name", "kind": "name", "weight": 1.0}],
        block=None,
    )
    assert "matches" in out
