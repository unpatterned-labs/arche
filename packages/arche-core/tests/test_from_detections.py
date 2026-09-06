# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Step 2 (engine reconciliation): the Detection -> Reference bridge.

The four hard rules: the two-boundary drop rule (restricted = usable for
matching, never disclosable), the category-precise person-vs-non-person table,
structured addresses surviving via Attribute.components, and the single-subject
warning. Plus the disclosure-boundary enforcement in attest and render.
"""

import pytest
from arche.canonical import (
    PERSON_ID_CATEGORIES,
    Reference,
    attribute_for_category,
)
from arche.render import render
from arche.resolve.coreference import _reference_to_match_record, coref_references
from arche.workflow._primitive import Pipeline

_KEY = b"bridge-test-issuer-key-32-bytes!"


def _ng_result(text="Fatima Abdullahi, NIN 12345678901, phone 08031234567."):
    return Pipeline(jurisdiction="NG").process(text)


# ── the mapping table ────────────────────────────────────────────────────────


def test_category_table_person_vs_non_person():
    assert attribute_for_category("PII-2-NIN") == "nin"
    assert attribute_for_category("PII-1-NAME") == "full_name"
    assert attribute_for_category("PII-3-EMAIL") == "email"
    # A company registration number is NOT a person identifier.
    assert attribute_for_category("PII-2-RC") == "rc"
    assert "PII-2-RC" not in PERSON_ID_CATEGORIES
    # Special-category / device / secret data never enters a reference.
    assert attribute_for_category("PII-6-HEALTH") is None
    assert attribute_for_category("PII-8-IP_ADDRESS") is None
    assert attribute_for_category("PII-8-PASSWORD") is None
    assert attribute_for_category("PII-5-CRYPTO_WALLET") is None


def test_rc_number_never_reaches_person_id_matching():
    # Even if an RC lands on the reference, it must not feed national_id.
    ref = Reference.from_record({"full_name": "Ada Obi", "rc": "RC123456"})
    record = _reference_to_match_record(ref)
    assert "national_id" not in record


# ── the bridge ───────────────────────────────────────────────────────────────


def test_from_detections_builds_reference_with_citations():
    result = _ng_result()
    ref = Reference.from_detections(result, source_system="clinic")
    names = {a.name for a in ref.attributes}
    assert "nin" in names and "phone" in names
    nin = next(a for a in ref.attributes if a.name == "nin")
    # Compliance provenance travels with the data.
    assert nin.provenance and "NDPA" in nin.provenance[0].regulatory_citation
    assert ref.source_system == "clinic"
    assert ref.record_id == result.document_hash


def test_bridge_feeds_matching_via_person_id_family():
    result_a = _ng_result()
    result_b = _ng_result("Patient Fatima Abdulahi (NIN 12345678901).")
    ra = Reference.from_detections(result_a, source_system="a")
    rb = Reference.from_detections(result_b, source_system="b")
    # The bridged nin attribute reaches the matcher's national_id field...
    assert _reference_to_match_record(ra).get("national_id") == "12345678901"
    # ...and the pair resolves.
    d = coref_references(ra, rb, jurisdiction="NG", issuer_key=_KEY)
    assert d.identity == "same_entity"


def test_shipped_statute_drop_categories_are_table_excluded():
    # Line of defense 1: every category the SHIPPED statutes `drop` (PII-5-CARD,
    # PII-6-*, PII-7-*, PII-8-PASSWORD) is excluded from references by the
    # mapping table itself — it can never ride in a resolution record at all.
    for cat in ("PII-5-CARD", "PII-6-HEALTH", "PII-6-RELIGION",
                "PII-7-FACE_TEMPLATE", "PII-8-PASSWORD"):
        assert attribute_for_category(cat) is None


def test_drop_actioned_mapped_category_becomes_restricted():
    # Line of defense 2 (the two-boundary rule): when an OPERATOR statute drops
    # a category that IS mapped (here: phone), the bridge keeps the value for
    # matching but marks it restricted — never disclosable.
    from types import SimpleNamespace

    det = SimpleNamespace(
        id="det:phone:0:11", category="PII-3-PHONE", text="08031234567",
        start=0, end=11, confidence=0.95, detector="rule:phone",
        regulatory_citation="OPERATOR-POLICY s.1", metadata={},
    )
    outcome = SimpleNamespace(detection_id="det:phone:0:11", action="drop")
    result = SimpleNamespace(
        detections=[det], policy_outcomes=[outcome],
        metadata={"statute_id": "OPERATOR", "statute_version": "1"},
        document_hash="doc-1",
    )
    ref = Reference.from_detections(result)
    phone = next(a for a in ref.attributes if a.name == "phone")
    assert phone.restricted is True
    # Still usable for matching...
    assert _reference_to_match_record(ref).get("phone") == "08031234567"
    # ...but never renderable.
    assert render(ref, reveal=True)["phone"] == "[RESTRICTED:PHONE]"


def test_single_subject_warning_on_multi_person_document():
    result = Pipeline(jurisdiction="NG").process(
        "Adaeze Obi met Chukwuemeka Okafor to sign the form."
    )
    names = {d.text for d in result.detections if d.category == "PII-1-NAME"}
    if len(names) < 2:
        pytest.skip("name detector found <2 names in fixture")
    with pytest.warns(UserWarning, match="ONE entity"):
        Reference.from_detections(result)


def test_address_components_survive_the_bridge():
    text = "Deliver to 12 Ahmadu Bello Way, Kaduna."
    result = Pipeline(jurisdiction="NG").process(text)
    addr_dets = [d for d in result.detections if d.category == "PII-4-ADDRESS"]
    if not addr_dets or not addr_dets[0].metadata:
        pytest.skip("address parser did not emit components for fixture")
    ref = Reference.from_detections(result)
    addr = next(a for a in ref.attributes if a.name == "address")
    assert addr.components  # structure preserved on the attribute
    record = _reference_to_match_record(ref)
    assert isinstance(record["address"], dict)  # dict form for compare_addresses


# ── disclosure boundaries: restricted is never disclosable ───────────────────


def _restricted_decision():
    a = Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "NIN-1"})
    b = Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "NIN-1"})
    for ref in (a, b):
        for attr in ref.attributes:
            if attr.name == "national_id":
                attr.restricted = True  # simulate a statute drop action
    return coref_references(a, b, jurisdiction="NG", issuer_key=_KEY)


def test_restricted_attribute_never_renders_even_with_reveal_true():
    ref = Reference.from_record({"full_name": "Ada Obi", "national_id": "NIN-9"})
    ref.attributes[1].restricted = True
    out = render(ref, reveal=True)
    assert out["national_id"] == "[RESTRICTED:NATIONAL_ID]"
    assert "NIN-9" not in str(out)
    assert out["full_name"] == "Ada Obi"          # non-restricted reveals normally


def test_restricted_still_usable_for_matching():
    d = _restricted_decision()
    assert d.identity == "same_entity"            # recall preserved
    assert d.factors.get("national_id") == 1.0    # the restricted id DID match


# ── codex-verification fixes (post-build NO-GO round) ────────────────────────


def test_as_record_fails_closed_on_restricted():
    # CRITICAL fix: flattening must not launder a restricted value into an
    # unguarded dict (render/egress can't see restriction on a plain dict).
    ref = Reference.from_record({"full_name": "Ada Obi", "phone": "08031234567"})
    next(a for a in ref.attributes if a.name == "phone").restricted = True
    rec = ref.as_record()
    assert "phone" not in rec                       # excluded by default
    assert "08031234567" not in str(render(rec, reveal=True))
    # Inside the trust boundary, matching can still opt in.
    assert ref.as_record(include_restricted=True)["phone"] == "08031234567"


def test_as_record_preserves_address_components():
    from types import SimpleNamespace
    det = SimpleNamespace(
        id="det:address:0:20", category="PII-4-ADDRESS",
        text="12 Bello Way, Kaduna", start=0, end=20, confidence=0.9,
        detector="rule:addr_parser", regulatory_citation=None,
        metadata={"street": "Bello Way", "city": "Kaduna", "anchor": None},
    )
    result = SimpleNamespace(detections=[det], policy_outcomes=[],
                             metadata={}, document_hash="d1")
    rec = Reference.from_detections(result).as_record()
    assert isinstance(rec["address"], dict)
    assert rec["address"]["city"] == "Kaduna"       # structure survives flattening


def test_to_match_record_is_category_precise():
    # CRITICAL fix: the legacy adapter must not map non-person PII-2 subtypes
    # (company RC, tax ids, DIDs) to national_id.
    from types import SimpleNamespace

    from arche.resolve._matcher import to_match_record

    def det(cat, text):
        return SimpleNamespace(category=cat, text=text, metadata={})

    rec = to_match_record([det("PII-2-RC", "RC123456"), det("PII-2-TIN", "T1"),
                           det("PII-2-DID", "did:key:xyz")])
    assert "national_id" not in rec
    rec2 = to_match_record([det("PII-2-NIN", "12345678901")])
    assert rec2["national_id"] == "12345678901"     # person ids still map


def test_african_detectors_blocked_even_with_explicit_detectors():
    # HIGH fix: the no-mislabel rule is ENFORCED, not just a default.
    with pytest.warns(UserWarning, match="skipped for jurisdiction 'DE'"):
        result = Pipeline(jurisdiction="DE", detectors=["africa", "core"]).process(
            "Steuer-ID: 12345678901"
        )
    assert not any(d.category.startswith("PII-2-") for d in result.detections)


def test_resolution_pipeline_includes_emails():
    # HIGH fix: the email-enabled resolution entry point exists.
    from arche.resolve.coreference import coref_from_pipeline, resolution_pipeline

    pipe = resolution_pipeline("DE")
    assert "emails" in pipe.detector_packages
    a = pipe.process("Kontakt j.mueller@firma.de, Fall 9912.")
    b = pipe.process("Antwort an j.mueller@firma.de bitte.")
    d = coref_from_pipeline(a, b, issuer_key=_KEY)
    assert d.factors.get("email") == 1.0            # email evidence reaches the gate
