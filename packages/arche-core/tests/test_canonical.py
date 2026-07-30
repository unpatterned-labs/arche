# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests canonical object model (``arche.canonical``).

Covers the collision-safe migration:
  * ``extract.Entity`` is aliased to ``EntityReference`` (both keep working).
  * the canonical resolved ``Entity`` is distinct and lives in ``arche.canonical``.
  * round-trip ``extract.Entity`` <-> ``EntityReference``.
  * ``ResolvedEntity`` -> canonical ``Entity`` carries attributes + citations.
  * identity vs descriptive attribute distinction.
"""

import pytest
from arche.extract import Entity as ExtractEntity
from arche.extract import extract
from arche.canonical import (
    IDENTITY_ATTRIBUTE_NAMES,
    Attribute,
    Entity,
    EntityReference,
    IdentityAttribute,
    ProvenanceCitation,
    Reference,
    canonical_entity_type,
    is_identity_attribute_name,
    make_attribute,
)
from arche.resolve.classical import ResolvedEntity

# ── Collision resolution ─────────────────────────────────────────────────────


def test_extract_entity_is_entity_reference():
    """extract.Entity must be the SAME class as EntityReference (deprecation shim)."""
    assert ExtractEntity is EntityReference


def test_canonical_entity_does_not_clobber_reference():
    """The canonical resolved Entity is a different type from the reference."""
    assert Entity is not EntityReference
    assert Entity is not ExtractEntity


def test_arche_top_level_entity_stays_the_reference():
    """``from arche import Entity`` must still resolve to the mention type."""
    import arche

    assert arche.Entity is EntityReference


# ── EntityReference: shape + masking parity with the legacy Entity ───────────


def test_reference_field_shape_matches_legacy():
    ref = EntityReference(text="Janet", entity_type="PERSON", confidence=0.9, start=0, end=5)
    assert ref.source == "regex"          # default preserved
    assert ref.metadata == {}             # default_factory preserved
    assert "PERSON" in repr(ref)


def test_reference_masks_pii_in_repr():
    ref = EntityReference(
        text="+234 803 555 7890", entity_type="PHONE", confidence=0.9, start=0, end=17
    )
    r = repr(ref)
    assert "+234 803 555 7890" not in r
    assert "+23***" in r


def test_reference_does_not_mask_non_pii():
    ref = EntityReference(
        text="Janet Okafor", entity_type="PERSON", confidence=0.9, start=0, end=12
    )
    assert "Janet Okafor" in repr(ref)


# ── Round-trip: extract.Entity <-> EntityReference ───────────────────────────


def test_round_trip_mention_to_reference_and_back():
    mention = ExtractEntity(
        text="12345678901",
        entity_type="NATIONAL_ID",
        confidence=0.97,
        start=4,
        end=15,
        source="african",
        metadata={"country": "NG", "id_type": "nin"},
    )
    ref = EntityReference.from_mention(mention)
    assert (ref.text, ref.entity_type, ref.confidence) == ("12345678901", "NATIONAL_ID", 0.97)
    assert (ref.start, ref.end, ref.source) == (4, 15, "african")
    assert ref.metadata == {"country": "NG", "id_type": "nin"}

    back = ref.to_mention()
    assert isinstance(back, ExtractEntity)
    assert back == mention  # dataclass equality: fields survive the round-trip


def test_round_trip_metadata_is_copied_not_shared():
    mention = ExtractEntity(text="x", entity_type="PERSON", confidence=1.0, start=0, end=1,
                            metadata={"k": "v"})
    ref = EntityReference.from_mention(mention)
    ref.metadata["k"] = "mutated"
    assert mention.metadata["k"] == "v"  # source untouched


def test_from_mention_accepts_a_reference_too():
    ref = EntityReference(text="a", entity_type="EMAIL", confidence=0.5, start=0, end=1)
    ref2 = EntityReference.from_mention(ref)
    assert ref2 == ref


def test_extract_output_is_entity_reference_instances():
    refs = extract("Email me at janet@example.com", backend="regex")
    assert refs, "expected at least one reference"
    assert all(isinstance(r, EntityReference) for r in refs)


# ── Attribute / IdentityAttribute distinction ────────────────────────────────


def test_identity_attribute_names_cover_core_identifiers():
    for name in ("nin", "bvn", "phone", "email", "national_id", "ghana_card"):
        assert is_identity_attribute_name(name)
    for name in ("full_name", "address", "date_of_birth", "gender", "amount"):
        assert not is_identity_attribute_name(name)


def test_make_attribute_dispatches_on_name():
    ident = make_attribute("national_id", "12345678901", 0.97)
    desc = make_attribute("full_name", "Janet Okafor", 0.9)
    assert isinstance(ident, IdentityAttribute) and ident.identifying is True
    assert isinstance(desc, Attribute) and not isinstance(desc, IdentityAttribute)
    assert desc.identifying is False


def test_identity_attribute_default_flag():
    a = IdentityAttribute(name="phone", value="+2348035557890")
    assert a.identifying is True


def test_case_insensitive_identifier_matching():
    assert is_identity_attribute_name("NIN")
    assert isinstance(make_attribute("PHONE", "x"), IdentityAttribute)


# ── ProvenanceCitation ───────────────────────────────────────────────────────


def test_provenance_from_reference_reads_metadata():
    ref = EntityReference(
        text="12345678901", entity_type="NATIONAL_ID", confidence=0.97, start=4, end=15,
        source="african",
        metadata={
            "regulatory_citation": "NDPA-2023 s.2.2",
            "statute_id": "NDPA-2023",
            "statute_version": "1.0",
        },
    )
    cite = ProvenanceCitation.from_reference(ref)
    assert cite.source == "african"
    assert cite.regulatory_citation == "NDPA-2023 s.2.2"
    assert cite.statute_id == "NDPA-2023"
    assert cite.span == (4, 15)


def test_provenance_no_law_is_not_an_error():
    ref = EntityReference(text="a", entity_type="PERSON", confidence=0.5, start=0, end=1)
    cite = ProvenanceCitation.from_reference(ref)
    assert cite.regulatory_citation == ""  # absence represented, no raise


# ── ResolvedEntity -> canonical Entity ───────────────────────────────────────


def _resolved_person_with_identifiers() -> ResolvedEntity:
    """A resolved cluster mixing a name mention with identifier mentions."""
    members = [
        ExtractEntity(text="Janet Okafor", entity_type="PERSON", confidence=0.95,
                      start=0, end=12, source="gliner"),
        ExtractEntity(text="Jan Okafor", entity_type="PERSON", confidence=0.90,
                      start=20, end=30, source="gliner"),
        ExtractEntity(text="12345678901", entity_type="NATIONAL_ID", confidence=0.97,
                      start=40, end=51, source="african",
                      metadata={"country": "NG", "id_type": "nin",
                                "regulatory_citation": "NDPA-2023 s.2.2"}),
        ExtractEntity(text="+2348035557890", entity_type="PHONE", confidence=0.90,
                      start=60, end=74, source="african",
                      metadata={"regulatory_citation": "NDPA-2023 s.2.2"}),
    ]
    return ResolvedEntity(
        canonical_name="Janet Okafor",
        entity_type="PERSON",
        aliases=["Jan Okafor"],
        confidence=0.93,
        sources=4,
        match_reasons=["merged_4_mentions", "national_id_match"],
        entities=members,
    )


def test_resolved_to_entity_basic_fields():
    ent = Entity.from_resolved(_resolved_person_with_identifiers())
    assert ent.canonical_name == "Janet Okafor"
    assert ent.entity_type == "person"                 # PERSON -> person
    assert len(ent.references) == 4
    assert all(isinstance(r, EntityReference) for r in ent.references)
    assert ent.confidence == 0.93
    assert "national_id_match" in ent.match_reasons


def test_resolved_to_entity_identity_vs_descriptive_split():
    ent = Entity.from_resolved(_resolved_person_with_identifiers())

    ident_names = {a.name for a in ent.identity_attributes}
    desc_names = {a.name for a in ent.descriptive_attributes}

    assert ident_names == {"national_id", "phone"}     # the distinguishing subset
    assert "full_name" in desc_names                   # a common name is descriptive
    assert all(a.identifying for a in ent.identity_attributes)
    assert all(not a.identifying for a in ent.descriptive_attributes)


def test_resolved_to_entity_carries_citations_onto_attributes():
    ent = Entity.from_resolved(_resolved_person_with_identifiers())

    nid = next(a for a in ent.identity_attributes if a.name == "national_id")
    assert nid.regulatory_citations == ["NDPA-2023 s.2.2"]
    assert nid.provenance[0].source == "african"

    # Entity-level flattening dedupes across attributes.
    assert ent.regulatory_citations == ["NDPA-2023 s.2.2"]


def test_resolved_to_entity_dedupes_repeated_values():
    """Two mentions of the same phone collapse to one attribute with merged provenance."""
    members = [
        ExtractEntity(text="+2348035557890", entity_type="PHONE", confidence=0.80,
                      start=0, end=14, source="regex",
                      metadata={"regulatory_citation": "NDPA-2023 s.2.2"}),
        ExtractEntity(text="+2348035557890", entity_type="PHONE", confidence=0.90,
                      start=30, end=44, source="african",
                      metadata={"regulatory_citation": "NDPA-2023 s.2.2"}),
    ]
    resolved = ResolvedEntity(
        canonical_name="+2348035557890", entity_type="PHONE", aliases=[],
        confidence=0.85, sources=2, match_reasons=["merged_2_mentions"], entities=members,
    )
    ent = Entity.from_resolved(resolved)
    phones = [a for a in ent.identity_attributes if a.name == "phone"]
    assert len(phones) == 1
    assert len(phones[0].provenance) == 2                 # both mentions cited
    assert phones[0].confidence == 0.90                   # highest confidence kept


def test_provenance_aggregation_at_entity_level():
    ent = Entity.from_resolved(_resolved_person_with_identifiers())
    # 4 references -> 4 attributes (2 names, 1 nid, 1 phone), each 1 citation.
    assert len(ent.provenance) == len(ent.attributes) == 4


def test_canonical_entity_type_mapping():
    assert canonical_entity_type("PERSON") == "person"
    assert canonical_entity_type("ORGANIZATION") == "organization"
    assert canonical_entity_type("LOCATION") == "place"
    assert canonical_entity_type("VEHICLE") == "vehicle"   # unknown -> lowercased thing


# ── End-to-end: extract -> resolve -> canonical model ────────────────────────


def test_end_to_end_extract_resolve_model():
    from arche.resolve import resolve_entities

    refs = extract("Contact Janet Okafor at janet@example.com", backend="regex")
    resolved = resolve_entities(refs, use_splink=False)
    entities = [Entity.from_resolved(r) for r in resolved]
    assert entities
    # The email should surface as an identity attribute somewhere.
    all_ident = {a.name for e in entities for a in e.identity_attributes}
    assert "email" in all_ident


def test_identity_attribute_names_is_frozen():
    assert isinstance(IDENTITY_ATTRIBUTE_NAMES, frozenset)
    with pytest.raises(AttributeError):
        IDENTITY_ATTRIBUTE_NAMES.add("nope")  # type: ignore[attr-defined]


# ── Reference — the record-level ER unit ─────────────────────────────────────


def test_reference_is_distinct_from_mention_and_entity():
    """A Reference (record) is neither a mention nor a resolved entity."""
    assert Reference is not EntityReference
    assert Reference is not Entity


def test_reference_from_record_structured_source():
    """A structured record needs no extraction: fields -> attributes, id kept aside."""
    ref = Reference.from_record(
        {"id": "R1", "full_name": "Fatima Abdullahi", "nin": "12345678901", "note": ""}
    )
    assert ref.record_id == "R1"
    # nin is an identifier -> identity attribute; full_name is descriptive.
    ident = {a.name for a in ref.identity_attributes}
    descr = {a.name for a in ref.descriptive_attributes}
    assert "nin" in ident
    assert "full_name" in descr
    # Empty values are dropped; id is not carried as an attribute.
    assert ref.get("note") is None
    assert ref.get("id") is None
    assert ref.get("nin") == "12345678901"


def test_reference_as_record_round_trips_to_reconcile_shape():
    """as_record() emits the {field: value} dict reconcile() consumes, id under 'id'."""
    ref = Reference.from_record({"id": "R1", "full_name": "Ada Obi", "phone": "08031234567"})
    record = ref.as_record()
    assert record["id"] == "R1"
    assert record["full_name"] == "Ada Obi"
    assert record["phone"] == "08031234567"


def test_reference_from_mentions_extracts_and_dedups():
    """Unstructured path: mentions -> attributes, repeated (attr, value) merges provenance."""
    m1 = EntityReference("janet@example.com", "EMAIL", 0.8, 0, 17, source="regex")
    m2 = EntityReference("janet@example.com", "EMAIL", 0.9, 40, 57, source="gliner")
    m3 = EntityReference("Janet Okafor", "PERSON", 0.95, 20, 32, source="gliner")
    ref = Reference.from_mentions([m1, m2, m3], record_id="DOC-7")

    assert ref.record_id == "DOC-7"
    # Two email mentions collapse to ONE attribute carrying BOTH citations.
    emails = [a for a in ref.attributes if a.value == "janet@example.com"]
    assert len(emails) == 1
    assert len(emails[0].provenance) == 2
    # ...and it keeps the highest confidence seen.
    assert emails[0].confidence == pytest.approx(0.9)
    # The email is an identity attribute; the person name is descriptive.
    assert "email" in {a.name for a in ref.identity_attributes}


def test_reference_feeds_reconcile():
    """End-to-end: two references with the same distinctive name co-refer.

    A Reference is the unit ER operates on; as_record() is the bridge to
    reconcile(), and a name (a distinctive comparator) clears the gate to a match.
    """
    from arche.resolve import reconcile

    a = Reference.from_record({"id": "A1", "full_name": "Ada Obi"})
    b = Reference.from_record({"id": "B1", "full_name": "Ada Obi"})
    result = reconcile(
        [a.as_record()],
        [b.as_record()],
        [{"field": "full_name", "kind": "name", "weight": 1.0}],
        block=None,
    )
    assert any(m["decision"] == "match" for m in result["matches"]), (
        "identical distinctive names should co-refer"
    )
