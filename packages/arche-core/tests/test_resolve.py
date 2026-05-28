"""Tests for entity resolution (fuzzy fallback)."""

from arche.extract import Entity
from arche.resolve import resolve_entities


def _make_entity(text: str, etype: str = "PERSON", **meta) -> Entity:
    return Entity(
        text=text, entity_type=etype, confidence=0.9,
        start=0, end=len(text), source="test", metadata=meta,
    )


def test_resolve_identical_entities():
    entities = [
        _make_entity("Janet Okafor"),
        _make_entity("Janet Okafor"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    # Should merge into one
    persons = [r for r in resolved if r.entity_type == "PERSON"]
    assert len(persons) == 1
    assert persons[0].sources == 2


def test_resolve_similar_names():
    entities = [
        _make_entity("Janet Okafor"),
        _make_entity("Janet N. Okafor"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    persons = [r for r in resolved if r.entity_type == "PERSON"]
    assert len(persons) == 1


def test_resolve_african_name_equivalence():
    entities = [
        _make_entity("Mohammed Diallo"),
        _make_entity("Mamadou Jallow"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    persons = [r for r in resolved if r.entity_type == "PERSON"]
    assert len(persons) == 1
    assert persons[0].sources == 2


def test_resolve_different_people():
    entities = [
        _make_entity("Janet Okafor"),
        _make_entity("David Mensah"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    persons = [r for r in resolved if r.entity_type == "PERSON"]
    assert len(persons) == 2


def test_resolve_exact_phone_match():
    entities = [
        _make_entity("+234 803 555 7890", "PHONE"),
        _make_entity("+2348035557890", "PHONE"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    phones = [r for r in resolved if r.entity_type == "PHONE"]
    assert len(phones) == 1
    assert phones[0].sources == 2


def test_resolve_single_entity():
    entities = [_make_entity("Fatima Abdullahi")]
    resolved = resolve_entities(entities, use_splink=False)
    assert len(resolved) == 1
    assert resolved[0].sources == 1


def test_resolve_empty_list():
    resolved = resolve_entities([], use_splink=False)
    assert resolved == []


def test_resolve_cross_system_fhir():
    """Entities from different FHIR patients sharing phone should be linked."""
    entities = [
        _make_entity("Fatima Abdullahi", patient_id="opencrvs-001"),
        _make_entity("+234 803 555 7890", "PHONE", patient_id="opencrvs-001"),
        _make_entity("Fatoumata Abdoulaye", patient_id="mosip-002"),
        _make_entity("+234 803 555 7890", "PHONE", patient_id="mosip-002"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    persons = [r for r in resolved if r.entity_type == "PERSON"]
    # The two person names should be merged (same phone + name equivalence)
    assert len(persons) == 1
    assert persons[0].sources == 2
