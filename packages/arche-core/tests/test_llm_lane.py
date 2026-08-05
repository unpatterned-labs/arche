# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The LLM lane: declaration-driven extraction + the evaluation harness.

Every test is offline — the model is an injected stub, which is itself the
point: the lane's contract is provider-agnostic ("bring your own model"), so
a plain callable must be a first-class citizen.
"""

from __future__ import annotations

import json
import warnings

import pytest
from arche import resolve
from arche.attest import attest, verify_attestation
from arche.declare import Declaration
from arche.llm.declarative import extract_declared
from arche.llm.harness import grade_extractions, grade_pairs
from arche.sign.keys import generate_keypair

DECL_RAW = {
    "arche_declaration": 1,
    "name": "fisheries-landings",
    "version": "1.2.0",
    "entity": "catch_lot",
    "id_field": "lot_id",
    "fields": {
        "supplier_name": {"role": "identifies", "kind": ["name", "tftoken"],
                          "weight": 2.0},
        "vessel_id": {"role": "identifies", "kind": "id", "id_family": "imo",
                      "weight": 3.0},
        "port": {"role": "describes", "kind": "name", "pii": False},
        "observer_notes": {"role": "ignore"},
    },
}


@pytest.fixture
def decl() -> Declaration:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Declaration.from_dict(DECL_RAW)


# ── extract_declared ─────────────────────────────────────────────────────────
def test_extraction_via_stub_model(decl):
    def fake_llm(messages):
        assert "catch_lot" in messages[0]["content"]        # prompt from decl
        assert decl.pin() in messages[0]["content"]         # pin in the prompt
        return ('```json\n{"supplier_name": "Acme Fisheries", '
                '"vessel_id": "IMO-9074729", "port": "Lagos"}\n```')

    ex = extract_declared("Landing sheet: Acme Fisheries, IMO-9074729, Lagos",
                          decl, complete_fn=fake_llm, model="stub-1")
    assert ex.violations == []
    assert ex.model == "stub-1"
    names = {a.name for a in ex.reference.attributes}
    assert names == {"supplier_name", "vessel_id", "port"}


def test_hallucinated_field_is_a_violation_not_a_value(decl):
    def fake_llm(messages):
        return json.dumps({"vessel_id": "IMO-1", "captain_ssn": "123-45-6789"})

    ex = extract_declared("...", decl, complete_fn=fake_llm)
    assert ex.violations == ["undeclared field 'captain_ssn'"]
    assert "captain_ssn" not in {a.name for a in ex.reference.attributes}


def test_bad_model_output_fails_loud(decl):
    with pytest.raises(ValueError, match="valid JSON"):
        extract_declared("...", decl, complete_fn=lambda m: "I think that...")
    with pytest.raises(ValueError, match="expected one JSON object"):
        extract_declared("...", decl, complete_fn=lambda m: "[1, 2]")
    with pytest.raises(ValueError, match="exactly one"):
        extract_declared("...", decl)                       # neither seam


def test_llm_decision_carries_honest_provenance_and_attests(decl):
    def fake_llm(messages):
        return json.dumps({"supplier_name": "Acme Fisheries",
                           "vessel_id": "IMO-9074729"})

    ex_a = extract_declared("doc a", decl, complete_fn=fake_llm, model="stub-1")
    ex_b = extract_declared("doc b", decl, complete_fn=fake_llm, model="stub-1")
    key = b"llm-lane-tests-issuer-key-32-byt"
    decision = resolve.pairwise(ex_a.reference, ex_b.reference,
                                issuer_key=key, decl=decl,
                                extra_pins=ex_a.pins(decl))
    assert decision.identity == "same_entity"               # shared vessel_id
    assert decision.pins["extraction"]["reproducible"] is False
    assert decision.pins["extraction"]["model"] == "stub-1"
    assert decision.pins["declaration"] == decl.pin()
    signed = attest(decision, generate_keypair(), mode="jws")
    assert verify_attestation(signed.compact).valid


# ── grade_pairs (the model as matcher, engine as oracle) ─────────────────────
SAME = ({"lot_id": "a1", "supplier_name": "Acme Fisheries",
         "vessel_id": "IMO-9074729"},
        {"lot_id": "b1", "supplier_name": "Acme Fisheries Ltd",
         "vessel_id": "IMO-9074729"})
DIFF = ({"lot_id": "a2", "supplier_name": "Acme Fisheries",
         "vessel_id": "IMO-9074729"},
        {"lot_id": "b2", "supplier_name": "Acme Fisheries",
         "vessel_id": "IMO-1111111"})


def test_perfect_judge_scores_full_agreement(decl):
    oracle = {"a1": "same", "a2": "different"}

    report = grade_pairs(decl, [SAME, DIFF],
                         lambda a, b: oracle[a["lot_id"]])
    assert report.total_pairs == 2
    assert report.agreement_rate == 1.0
    assert report.divergences == []


def test_contrarian_judge_diverges_with_evidence(decl):
    flipped = {"same": "different", "different": "same"}
    oracle = {"a1": "same", "a2": "different"}

    report = grade_pairs(decl, [SAME, DIFF],
                         lambda a, b: flipped[oracle[a["lot_id"]]])
    assert report.agreement_rate == 0.0
    assert len(report.divergences) == 2
    d = report.divergences[0]
    assert d.engine in ("same_entity", "different")
    assert d.evidence                                       # engine's working

def test_unsure_and_review_are_abstentions_not_errors(decl):
    review_pair = ({"lot_id": "a3", "supplier_name": "Acme Fisheries"},
                   {"lot_id": "b3", "supplier_name": "Acme Fisheries"})
    report = grade_pairs(decl, [SAME, review_pair],
                         lambda a, b: "unsure" if a["lot_id"] == "a1"
                         else "same")
    # SAME scored but judge unsure -> excluded; review_pair may abstain.
    assert report.judge_unsure + report.engine_abstained >= 1
    assert report.agreement_rate is None or 0.0 <= report.agreement_rate <= 1.0


def test_judge_answer_vocabulary_is_closed(decl):
    with pytest.raises(ValueError, match="judge returned"):
        grade_pairs(decl, [SAME], lambda a, b: "probably")


# ── grade_extractions (the model as extractor: contract metrics) ─────────────
def test_extraction_grading_reports_coverage_and_violations(decl):
    def good(messages):
        return json.dumps({"supplier_name": "Acme", "vessel_id": "IMO-1"})

    def sloppy(messages):
        return json.dumps({"vessel_id": "IMO-2", "made_up": "x"})

    exs = [extract_declared("t1", decl, complete_fn=good),
           extract_declared("t2", decl, complete_fn=sloppy)]
    stats = grade_extractions(exs, decl)
    assert stats["records"] == 2
    assert stats["records_with_violations"] == 1
    assert stats["violation_rate"] == 0.5
    assert stats["field_coverage"]["vessel_id"] == 1.0
    assert stats["field_coverage"]["supplier_name"] == 0.5
    assert stats["declaration"] == decl.pin()
