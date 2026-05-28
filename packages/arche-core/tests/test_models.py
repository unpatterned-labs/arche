"""Tests for Pydantic v2 models and adapters."""

import pytest
from arche.extract import Entity
from arche.models import (
    IdentityEvidenceModel,
    IdentityRecordModel,
    JurisdictionProfileModel,
    MatchDecisionModel,
    SensitiveSpanModel,
    entity_to_evidence_model,
    evidence_from_dataclass,
    evidence_to_dataclass,
    pii_to_span_model,
    record_from_dataclass,
    resolved_to_record_model,
    span_from_dataclass,
)
from arche.protect import PIIDetection
from arche.resolve import ResolvedEntity
from arche.types import (
    IdentityEvidence,
    IdentityRecord,
    SensitiveSpan,
)

# ── Model creation and validation ───────────────────────────────────────────


def test_identity_evidence_model_creation():
    ev = IdentityEvidenceModel(
        text="12345678901",
        label="nin",
        confidence=0.95,
        start=0,
        end=11,
        detector_source="african",
        country_hint="NG",
        validator_status="format_valid",
    )
    assert ev.text == "12345678901"
    assert ev.label == "nin"
    assert ev.confidence == 0.95
    assert ev.country_hint == "NG"


def test_identity_evidence_model_defaults():
    ev = IdentityEvidenceModel(text="test", label="person", confidence=0.8, start=0, end=4)
    assert ev.detector_source == "regex"
    assert ev.country_hint == ""
    assert ev.validator_status == "unchecked"
    assert ev.document_id == ""
    assert ev.metadata == {}


def test_identity_evidence_model_validation():
    with pytest.raises(Exception):
        IdentityEvidenceModel(text="x", label="y", confidence=1.5, start=0, end=1)
    with pytest.raises(Exception):
        IdentityEvidenceModel(text="x", label="y", confidence=-0.1, start=0, end=1)


def test_sensitive_span_model():
    span = SensitiveSpanModel(
        text="test@example.com",
        label="email",
        confidence=0.95,
        start=0,
        end=16,
        redaction="mask",
    )
    assert span.redaction == "mask"
    assert span.detector_source == "regex"


def test_match_decision_model():
    md = MatchDecisionModel(
        cluster_id="cluster-0",
        confidence=0.92,
        factor_breakdown={"name_similarity": 0.92, "phone_match": 1.0},
        reviewer_explanation="Matched via name similarity and phone",
    )
    assert md.factor_breakdown["name_similarity"] == 0.92
    assert "cluster-0" in repr(md)


def test_identity_record_model():
    record = IdentityRecordModel(
        cluster_id="cluster-0",
        canonical_name="Janet Okafor",
        names=["Janet Okafor", "Janet N. Okafor"],
        identifiers=[{"system": "NIMC", "value": "12345678901", "country": "NG", "type": "NIN"}],
        telecom=[{"system": "phone", "value": "+2348035557890"}],
        confidence=0.95,
        match_reasons=["name_similarity:0.92"],
    )
    assert record.canonical_name == "Janet Okafor"
    assert len(record.names) == 2
    assert record.identifiers[0]["country"] == "NG"


def test_jurisdiction_profile_model():
    profile = JurisdictionProfileModel(
        country_code="NG",
        country_name="Nigeria",
        version="0.1.0",
    )
    assert profile.country_code == "NG"
    assert "NG" in repr(profile)


def test_model_serialization():
    ev = IdentityEvidenceModel(
        text="Fatima", label="person", confidence=0.9, start=0, end=6,
    )
    d = ev.model_dump()
    assert d["text"] == "Fatima"
    assert d["confidence"] == 0.9

    # Round-trip
    ev2 = IdentityEvidenceModel.model_validate(d)
    assert ev2.text == ev.text


# ── Adapter tests: dataclass ↔ Pydantic ────────────────────────────────────


def test_evidence_dataclass_roundtrip():
    dc = IdentityEvidence(
        text="12345678901", label="nin", confidence=0.95,
        start=0, end=11, detector_source="african",
        country_hint="NG", validator_status="format_valid",
    )
    model = evidence_from_dataclass(dc)
    assert isinstance(model, IdentityEvidenceModel)
    assert model.text == dc.text
    assert model.country_hint == "NG"

    # Back to dataclass
    dc2 = evidence_to_dataclass(model)
    assert isinstance(dc2, IdentityEvidence)
    assert dc2.text == dc.text
    assert dc2.country_hint == dc.country_hint


def test_span_from_dataclass():
    dc = SensitiveSpan(
        text="test@email.com", label="email", confidence=0.9,
        start=0, end=14, redaction="hash",
    )
    model = span_from_dataclass(dc)
    assert isinstance(model, SensitiveSpanModel)
    assert model.redaction == "hash"


def test_record_from_dataclass():
    ev1 = IdentityEvidence(
        text="Janet", label="person", confidence=0.9,
        start=0, end=5,
    )
    dc = IdentityRecord(
        cluster_id="c1",
        canonical_name="Janet Okafor",
        names=["Janet Okafor"],
        confidence=0.9,
        evidence=[ev1],
    )
    model = record_from_dataclass(dc)
    assert isinstance(model, IdentityRecordModel)
    assert model.canonical_name == "Janet Okafor"
    assert len(model.evidence) == 1


# ── v1 → v2 adapter tests ──────────────────────────────────────────────────


def test_entity_to_evidence_model():
    entity = Entity(
        text="Fatima Abdullahi", entity_type="PERSON",
        confidence=0.85, start=0, end=16,
        source="gliner", metadata={"country": "NG"},
    )
    model = entity_to_evidence_model(entity)
    assert isinstance(model, IdentityEvidenceModel)
    assert model.label == "person"
    assert model.detector_source == "gliner"
    assert model.country_hint == "NG"


def test_pii_to_span_model():
    pii = PIIDetection(
        text="test@email.com", pii_type="EMAIL",
        confidence=0.95, start=0, end=14, country=None,
    )
    model = pii_to_span_model(pii)
    assert isinstance(model, SensitiveSpanModel)
    assert model.label == "email"


def test_resolved_to_record_model():
    entities = [
        Entity(text="Janet Okafor", entity_type="PERSON", confidence=0.9,
               start=0, end=12, source="test", metadata={"patient_id": "p1"}),
        Entity(text="+2348035557890", entity_type="PHONE", confidence=0.9,
               start=14, end=28, source="test", metadata={"patient_id": "p1"}),
    ]
    resolved = ResolvedEntity(
        canonical_name="Janet Okafor",
        entity_type="PERSON",
        aliases=[],
        confidence=0.9,
        sources=2,
        match_reasons=["phone_match"],
        entities=entities,
    )
    model = resolved_to_record_model(resolved)
    assert isinstance(model, IdentityRecordModel)
    assert model.canonical_name == "Janet Okafor"
    assert len(model.telecom) == 1
    assert model.telecom[0]["system"] == "phone"
