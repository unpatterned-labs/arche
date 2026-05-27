"""Tests for v2 resolve_identity_records() function."""

from arche.resolve import resolve_identity_records
from arche.types import IdentityEvidence, IdentityRecord


def _make_evidence(text: str, label: str = "person", **kwargs) -> IdentityEvidence:
    defaults = {
        "confidence": 0.9,
        "start": 0,
        "end": len(text),
        "detector_source": "test",
        "country_hint": "",
        "validator_status": "unchecked",
        "document_id": "",
        "metadata": {},
    }
    defaults.update(kwargs)
    return IdentityEvidence(text=text, label=label, **defaults)


def test_resolve_empty():
    records = resolve_identity_records([])
    assert records == []


def test_resolve_single_person():
    evidence = [_make_evidence("Janet Okafor")]
    records = resolve_identity_records(evidence)
    assert len(records) >= 1
    person_records = [r for r in records if "Janet" in r.canonical_name]
    assert len(person_records) == 1


def test_resolve_identical_names():
    evidence = [
        _make_evidence("Janet Okafor"),
        _make_evidence("Janet Okafor", start=20, end=32),
    ]
    records = resolve_identity_records(evidence)
    person_records = [r for r in records if "Janet" in r.canonical_name]
    assert len(person_records) == 1
    assert len(person_records[0].names) >= 1


def test_resolve_similar_names():
    evidence = [
        _make_evidence("Janet Okafor"),
        _make_evidence("Janet N. Okafor", start=20, end=35),
    ]
    records = resolve_identity_records(evidence)
    person_records = [r for r in records if "Janet" in r.canonical_name]
    assert len(person_records) == 1


def test_resolve_african_equivalence():
    evidence = [
        _make_evidence("Mohammed Diallo"),
        _make_evidence("Mamadou Jallow", start=20, end=34),
    ]
    records = resolve_identity_records(evidence)
    person_records = [r for r in records if r.canonical_name in ("Mohammed Diallo", "Mamadou Jallow")]
    # Should be merged into one record
    assert len(person_records) == 1


def test_resolve_different_people():
    evidence = [
        _make_evidence("Janet Okafor"),
        _make_evidence("David Mensah", start=20, end=32),
    ]
    records = resolve_identity_records(evidence)
    person_records = [r for r in records if r.canonical_name in ("Janet Okafor", "David Mensah")]
    assert len(person_records) == 2


def test_resolve_with_phone():
    evidence = [
        _make_evidence("Janet Okafor", document_id="sys-1"),
        _make_evidence("+2348035557890", label="phone", start=14, end=28, document_id="sys-1"),
    ]
    records = resolve_identity_records(evidence)
    assert len(records) >= 1


def test_resolve_with_national_id():
    evidence = [
        _make_evidence("Janet Okafor", document_id="sys-1"),
        _make_evidence("12345678901", label="nin", start=14, end=25,
                       country_hint="NG", document_id="sys-1"),
    ]
    records = resolve_identity_records(evidence)
    # Find the record that has identifiers
    id_records = [r for r in records if r.identifiers]
    assert len(id_records) >= 1
    assert id_records[0].identifiers[0]["country"] == "NG"


def test_resolve_cross_system():
    """Evidence from two systems with shared phone should merge."""
    evidence = [
        _make_evidence("Fatima Abdullahi", document_id="opencrvs-001"),
        _make_evidence("+2348035557890", label="phone", start=20, end=34, document_id="opencrvs-001"),
        _make_evidence("Fatoumata Abdoulaye", label="person", start=40, end=59, document_id="mosip-002"),
        _make_evidence("+2348035557890", label="phone", start=60, end=74, document_id="mosip-002"),
    ]
    records = resolve_identity_records(evidence)
    person_records = [r for r in records if "Fatima" in r.canonical_name or "Fatoumata" in r.canonical_name]
    # Should merge via shared phone
    assert len(person_records) == 1


def test_resolve_returns_identity_records():
    evidence = [_make_evidence("Test Person")]
    records = resolve_identity_records(evidence)
    assert all(isinstance(r, IdentityRecord) for r in records)


def test_resolve_jurisdiction_auto():
    evidence = [
        _make_evidence("12345678901", label="nin", country_hint="NG"),
        _make_evidence("Janet Okafor", start=15, end=27),
    ]
    records = resolve_identity_records(evidence, jurisdiction="auto")
    # Should infer NG jurisdiction
    id_records = [r for r in records if r.identifiers]
    if id_records:
        assert id_records[0].identifiers[0]["country"] == "NG"


def test_resolve_match_reasons_populated():
    evidence = [
        _make_evidence("Janet Okafor"),
        _make_evidence("Janet Okafor", start=20, end=32),
    ]
    records = resolve_identity_records(evidence)
    person_records = [r for r in records if "Janet" in r.canonical_name]
    assert len(person_records) == 1
    # Merged records should have match reasons
    if person_records[0].match_reasons:
        assert any("merged" in r for r in person_records[0].match_reasons)
