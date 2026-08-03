# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Correctness tests for the co-reference decision core (`arche.resolve.coreference`).

These pin the plan's §4/§5.1 guarantees: the distinctive-signal gate (C4), the
no-lone-identifier-merge guard and placeholder-DOB handling (H4), the id-conflict
veto, and reproducible/keyless ``decision_id`` with a keyed, Tier-1-only
``entity_id``.

S1-S7 mirror the scenarios in the build spec.
"""

from arche.canonical import Reference
from arche.resolve.coreference import (
    CoReferenceDecision,
    _is_placeholder_dob,
    _reference_to_match_record,
    coref_documents,
    coref_references,
)


def _ref(source_system: str = "", **fields) -> Reference:
    """Build a structured reference from ``{field: value}``."""
    ref = Reference.from_record(fields)
    ref.source_system = source_system
    return ref


# ── adapter ──────────────────────────────────────────────────────────────────


def test_reference_to_match_record_maps_and_takes_first():
    ref = _ref(full_name="Ada Obi", nin="A123", phone_number="0803", email="a@b.co")
    rec = _reference_to_match_record(ref)
    assert rec == {
        "name": "Ada Obi",
        "national_id": "A123",
        "phone": "0803",
        "email": "a@b.co",
    }


def test_placeholder_dob_detection():
    for placeholder in ("01-01", "0000-00-00", "0000", "1990", "", "00/00/0000"):
        assert _is_placeholder_dob(placeholder), placeholder
    for real in ("1990-05-12", "12/05/1990", "1990-1-1"):
        assert not _is_placeholder_dob(real), real


# ── S1: distinctive name + shared national_id -> same_entity, merge ──────────


def test_s1_distinctive_name_and_shared_id_merges():
    a = _ref(full_name="Ngozi Okonkwo", national_id="NG-77X")
    b = _ref(full_name="Ngozi Okonkwo", national_id="NG-77X")
    d = coref_references(a, b, jurisdiction="NG")
    assert d.identity == "same_entity"
    assert d.action == "merge"
    # two distinctive signals cleared the gate (the id and the rare name token)
    assert d.gate["distinctive_cleared"] is True
    assert d.factors["name_tf"] >= 0.75


# ── S2: lone shared national_id, nothing corroborating -> same_entity, hold ──


def test_s2_lone_identifier_holds():
    # A second field (name) is PRESENT so applied_fields >= 2 (required to assert
    # same_entity), but it disagrees, so nothing corroborates the lone id.
    a = _ref(full_name="John", national_id="A-123")
    b = _ref(full_name="Peter", national_id="A-123")
    d = coref_references(a, b, jurisdiction="NG")
    assert d.identity == "same_entity"
    assert d.action == "hold"
    assert d.basis == "single_identifier"
    assert d.gate["clearing_signal"] == "national_id"


# ── S3: same COMMON full name only -> review (gate NOT cleared, C4) ──────────


def test_s3_common_name_only_is_review():
    a = _ref(full_name="Ibrahim Musa")
    b = _ref(full_name="Ibrahim Musa")
    d = coref_references(a, b, jurisdiction="NG")
    assert d.identity == "review"
    assert d.action == "no_op"
    # weighted_token_sim is 1.0 for identical names, but the shared tokens are
    # common, so the distinctive gate must NOT clear.
    assert d.gate["distinctive_cleared"] is False
    assert d.factors["name_tf"] == 1.0  # confirms the naive signal would misfire


# ── S4: different national_ids -> different (id_conflict veto) ───────────────


def test_s4_id_conflict_vetoes_to_different():
    a = _ref(full_name="Ada Obi", national_id="A-1")
    b = _ref(full_name="Ada Obi", national_id="B-2")
    d = coref_references(a, b, jurisdiction="NG")
    assert d.identity == "different"
    assert d.action == "no_op"
    assert d.vetoes["id_conflict"] is True


# ── S5: placeholder DOB on both -> dropped, resolves on the real signals ─────


def test_s5_placeholder_dob_is_dropped():
    a = _ref(full_name="Ngozi Okonkwo", national_id="NG-1", dob="01-01")
    b = _ref(full_name="Ngozi Okonkwo", national_id="NG-1", dob="01-01")
    d = coref_references(a, b, jurisdiction="NG")
    # dob was a placeholder: neither an agreeing factor nor a conflict.
    assert "dob" not in d.factors
    assert d.gate["clearing_signal"] != "dob+name"
    # still resolves on name + national_id
    assert d.identity == "same_entity"


def test_s5_placeholder_dob_never_manufactures_agreement():
    # Without a real corroborator, a placeholder DOB must not let a lone id merge.
    a = _ref(full_name="John", national_id="A-1", dob="0000-00-00")
    b = _ref(full_name="Peter", national_id="A-1", dob="0000-00-00")
    d = coref_references(a, b, jurisdiction="NG")
    assert "dob" not in d.factors
    assert d.action == "hold"  # dob did NOT corroborate


# ── S6: decision_id reproducible; entity_id keyed + Tier-1 only ──────────────


def test_s6_decision_id_is_reproducible():
    a = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    b = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    d1 = coref_references(a, b, jurisdiction="NG")
    d2 = coref_references(a, b, jurisdiction="NG")
    assert d1.decision_id == d2.decision_id
    assert d1.decision_id.startswith("dec:sha256:")


def test_s6_entity_id_none_without_shared_exact_id():
    a = _ref(full_name="Ngozi Okonkwo", address="12 Bello Way")
    b = _ref(full_name="Ngozi Okonkwo", address="12 Bello Way")
    d = coref_references(a, b, jurisdiction="NG", issuer_key=b"x" * 32)
    assert d.entity_id is None  # fuzzy-only -> no Tier-1 pseudonym (H3)


def test_s6_entity_id_set_with_shared_id_and_key():
    a = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    b = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    d = coref_references(a, b, jurisdiction="NG", issuer_key=b"x" * 32)
    assert d.entity_id is not None
    assert d.entity_id.startswith("ent:hmac:")


def test_s6_entity_id_absent_without_key():
    a = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    b = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    d = coref_references(a, b, jurisdiction="NG")  # SDK stays keyless
    assert d.entity_id is None


# ── S7: decision_id is a pure function of the evidence (no objects/timestamps) ─


def test_s7_decision_id_excludes_reference_objects_and_time():
    # Two INDEPENDENT Reference objects with identical content must produce the
    # same decision_id — proving object identity / creation time never leak in.
    a1 = _ref(full_name="Amina Bello", national_id="KD-42")
    b1 = _ref(full_name="Amina Bello", national_id="KD-42")
    a2 = _ref(full_name="Amina Bello", national_id="KD-42")
    b2 = _ref(full_name="Amina Bello", national_id="KD-42")
    d1 = coref_references(a1, b1, jurisdiction="NG")
    d2 = coref_references(a2, b2, jurisdiction="NG")
    assert d1.decision_id == d2.decision_id
    # the reference objects are retained for rendering but are distinct instances
    assert d1.reference_a is a1
    assert d2.reference_a is a2
    assert d1.reference_a is not d2.reference_a


def test_s7_decision_id_changes_with_evidence():
    a = _ref(full_name="Amina Bello", national_id="KD-42")
    b_same = _ref(full_name="Amina Bello", national_id="KD-42")
    b_diff = _ref(full_name="Amina Bello", national_id="KD-99")
    d_same = coref_references(a, b_same, jurisdiction="NG")
    d_diff = coref_references(a, b_diff, jurisdiction="NG")
    assert d_same.decision_id != d_diff.decision_id


# ── return-type + pins surface ───────────────────────────────────────────────


def test_returns_decision_with_pins():
    a = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    b = _ref(full_name="Ngozi Okonkwo", national_id="NG-9")
    d = coref_references(a, b, jurisdiction="NG")
    assert isinstance(d, CoReferenceDecision)
    assert d.pins["jurisdiction"] == "NG"
    assert d.pins["tf"] == "default"
    assert d.pins["thresholds"]["distinctive_floor"] == 0.75
    assert "@" in d.pins["comparator_lib"] or d.pins["comparator_lib"] == "exact@builtin"
    assert d.field_weights["national_id"]["sim"] == 1.0


# ── coref_documents: extraction hop is provenance, not reproduction (H2) ─────


def test_coref_documents_records_provenance_out_of_decision_id():
    doc = "Contact NIN 12345678901, phone 08035557890."
    d1 = coref_documents(doc, doc, jurisdiction="NG", backend="regex")
    d2 = coref_documents(doc, doc, jurisdiction="NG", backend="regex")
    assert isinstance(d1, CoReferenceDecision)
    # document ids are recorded as provenance...
    prov = d1.pins["provenance"]
    assert prov["document_content_id_a"].startswith("doc:sha256:")
    assert prov["document_content_id_b"].startswith("doc:sha256:")
    # ...and the Reference-onward decision reproduces across identical extractions
    assert d1.decision_id == d2.decision_id
