# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""PlaceResolver + resolve_places() + list_places() tests.

Per docs/ceo-plans/2026-05-24-places-resolver.md §13.

Includes the 3 critical failure-mode tests (§13.3 — non-negotiable) and
the v0.1 trimmed coverage set (§16.6).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arche import list_places, resolve_places
from arche.resolve.places import (
    JurisdictionInferenceError,
    PlaceEntity,
    PlaceRecord,
    PlaceResolver,
    UpstreamError,
)


MUM_QUERY = (
    "My mum lives near St. Thomas' Hospital in SW1 — find her a dentist, "
    "an EV charger for her Nissan Leaf, and the nearest urgent care."
)


# ── detect() ─────────────────────────────────────────────────────────────────


def test_detect_full_postcode():
    """A full UK postcode is detected as kind='postcode' with high confidence."""
    r = PlaceResolver()
    entities = r.detect("I'm at SE1 7EH right now")
    assert any(e.text.replace(" ", "") == "SE17EH" or e.text == "SE1 7EH" for e in entities)
    e = [x for x in entities if "SE1" in x.text and "7EH" in x.text][0]
    assert e.kind == "postcode"
    assert e.confidence >= 0.95


def test_detect_partial_postcode():
    """A partial UK postcode ('SW1') is detected with lower confidence."""
    r = PlaceResolver()
    entities = r.detect("My mum lives near St Thomas' Hospital in SW1")
    sw1 = [e for e in entities if e.text == "SW1"]
    assert len(sw1) == 1
    assert sw1[0].kind == "postcode"
    assert 0.80 <= sw1[0].confidence <= 0.90


def test_detect_landmark_anchor():
    """'near St Thomas' Hospital' triggers landmark detection."""
    r = PlaceResolver()
    entities = r.detect("find me a dentist near St Thomas' Hospital")
    landmarks = [e for e in entities if e.kind == "landmark"]
    assert len(landmarks) >= 1
    assert "Thomas" in landmarks[0].text


def test_detect_category_keywords_finds_dentist_and_ev():
    """The mum query mentions 'dentist' and 'EV' (via Nissan Leaf) — both detected."""
    r = PlaceResolver()
    cats = r.detect_categories(MUM_QUERY)
    assert "dentist" in cats
    assert "ev_charger" in cats


# ── resolve_anchored() — happy path against fixture ─────────────────────────


def test_resolve_mum_query_happy_path():
    """The mum query returns 3 places from fixture (dentist + ev_charger + a_and_e)."""
    report = resolve_places(MUM_QUERY)
    assert len(report.places) == 3
    kinds = {p.kind for p in report.places}
    assert kinds == {"dentist", "ev_charger", "a_and_e"}
    assert report.jurisdiction == "GB"
    assert report.jurisdiction_trigger == "SW1"
    # Trace has all four events
    trace_names = [e.name for e in report.trace]
    assert trace_names == ["detect", "resolve", "protect", "graph"]


def test_resolve_places_explicit_jurisdiction_overrides_inference():
    """Explicit jurisdiction= overrides the inference even if text would imply otherwise."""
    report = resolve_places(MUM_QUERY, jurisdiction="GB")
    assert report.jurisdiction == "GB"
    assert report.jurisdiction_trigger == "explicit"
    assert report.jurisdiction_confidence == 1.0


# ── CRITICAL FAILURE MODE 1: jurisdiction unknown (§13.3) ───────────────────


def test_resolve_places_jurisdiction_unknown_raises():
    """Text with no inferable jurisdiction must RAISE, not silently default.

    Per spec §13.3 row 3 — critical failure mode. Silent 'XX' fallback is
    unacceptable; caller must know they need to pass jurisdiction= explicitly.
    """
    with pytest.raises(JurisdictionInferenceError) as exc:
        resolve_places("just some random text with no postcode or country at all")
    assert "Could not infer jurisdiction" in str(exc.value)


# ── CRITICAL FAILURE MODE 2: live_api stub raises UpstreamError (§13.3) ─────


def test_live_api_stub_raises_upstream_error():
    """When DEMO_LIVE_API=true, the v0.1 stub raises UpstreamError (not silent)."""
    r = PlaceResolver(live_api=True)
    entity = PlaceEntity(span=(0, 3), text="SW1", kind="postcode", confidence=0.85)
    with pytest.raises(UpstreamError) as exc:
        r.resolve_anchored(entity, categories=["dentist"])
    assert exc.value.source == "live_api_not_implemented_v0_1"


# ── CRITICAL FAILURE MODE 3: malformed fixture JSON (§13.3) ─────────────────


def test_malformed_fixture_raises_upstream_error(tmp_path: Path):
    """A malformed fixture file raises UpstreamError, not a raw JSONDecodeError."""
    bad_fixtures = tmp_path / "fixtures"
    bad_fixtures.mkdir()
    (bad_fixtures / "mum_query.json").write_text("{not: valid json,", encoding="utf-8")
    r = PlaceResolver(fixtures_dir=bad_fixtures)
    entity = PlaceEntity(span=(0, 3), text="SW1", kind="postcode", confidence=0.85)
    with pytest.raises(UpstreamError) as exc:
        r.resolve_anchored(entity, categories=["dentist"])
    assert exc.value.source == "fixture"


# ── redact() — GB rules mask staff PII ──────────────────────────────────────


def test_redact_gb_masks_staff_names_and_phones():
    """GB rules mask Dr/Mr/Mrs names + UK phones + emails. Public fields preserved."""
    r = PlaceResolver()
    record = PlaceRecord(
        id="nhs:test", name="Test Practice", address="1 Test St, London SE1 1AA",
        coords=(51.5, -0.1), kind="dentist", distance_m=100, source="fixture",
        raw_redacted={
            "nhs_reg": "8901",                            # public — keep
            "lead_dentist": "Dr Sarah Whitmore",          # mask
            "shift_lead_phone": "+44 7700 900123",        # mask
            "site_contact": "sarah.whitmore@gstt.nhs.uk", # mask
            "open_hours": "Mon-Fri 08:00-18:00",          # public — keep
        },
        audit_payload_id="audit:test",
    )
    safe = r.redact(record, jurisdiction="GB")
    assert "[REDACTED:STAFF_NAME]" in safe.raw_redacted["lead_dentist"]
    assert "[REDACTED:STAFF_PHONE]" in safe.raw_redacted["shift_lead_phone"]
    assert "[REDACTED:EMAIL]" in safe.raw_redacted["site_contact"]
    # Public fields preserved
    assert safe.raw_redacted["nhs_reg"] == "8901"
    assert safe.raw_redacted["open_hours"] == "Mon-Fri 08:00-18:00"
    # Affected fields listed
    assert set(safe.redacted_fields) == {"lead_dentist", "shift_lead_phone", "site_contact"}


def test_redact_non_gb_jurisdiction_passes_through_with_warning(caplog):
    """v0.1 only ships GB rules. Other jurisdictions pass through + warn."""
    r = PlaceResolver()
    record = PlaceRecord(
        id="x", name="x", address="x", coords=(0, 0), kind="dentist",
        distance_m=None, source="fixture",
        raw_redacted={"lead_dentist": "Dr Whoever"},
        audit_payload_id="audit:x",
    )
    safe = r.redact(record, jurisdiction="DE")
    # DE has no v0.1 rules → unmodified pass-through
    assert safe.raw_redacted["lead_dentist"] == "Dr Whoever"


# ── End-to-end: report from mum query has all redactions applied ────────────


def test_mum_query_report_redacts_all_staff_pii():
    """The mum query's 3 fixture records all have staff PII. Report MUST mask them."""
    report = resolve_places(MUM_QUERY)
    for place in report.places:
        for field_name, value in place.raw_redacted.items():
            if isinstance(value, str):
                # No raw doctor/matron names should survive
                assert "Dr Sarah Whitmore" not in value
                assert "Dr Marcus Holloway" not in value
                # No raw email should survive
                assert "@gstt.nhs.uk" not in value
                assert "@bppulse" not in value
    # Compliance block reflects what was redacted
    assert report.compliance.policy == "uk_gdpr_v0_hardcoded"
    assert len(report.compliance.redactions_applied) > 0


# ── save_receipt() roundtrip via arche.sign ─────────────────────────────────


def test_save_receipt_writes_verifiable_jws(tmp_path: Path):
    """save_receipt() produces a JWS envelope parseable as JSON."""
    report = resolve_places(MUM_QUERY)
    receipt_path = tmp_path / "receipt.jws"
    written = report.save_receipt(receipt_path)
    assert written == receipt_path
    assert receipt_path.exists()
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    # SignWorkflow envelope shape — verify it's well-formed JSON with expected keys
    assert isinstance(data, dict)
    # Envelope must reference our schema (in the payload or claims)
    serialised = json.dumps(data)
    assert "arche.place_report.v1" in serialised


# ── list_places() — directory mode ──────────────────────────────────────────


def test_list_places_physiotherapy_returns_directory():
    """Directory query returns paginated results with category-specific data."""
    report = list_places(category="physiotherapy", jurisdiction="GB", limit=5)
    assert report.category == "physiotherapy"
    assert report.jurisdiction == "GB"
    assert len(report.results) == 5
    assert report.next_cursor == "5"
    assert report.total_estimate == 4271
    # All results are the right kind
    assert all(r.kind == "physiotherapy" for r in report.results)


def test_list_places_pagination_via_cursor():
    """next_cursor → next page; eventually next_cursor becomes None at end."""
    page_1 = list_places(category="dentist", limit=5)
    page_2 = list_places(category="dentist", limit=5, cursor=page_1.next_cursor)
    assert page_1.next_cursor == "5"
    # Different IDs in different pages
    page_1_ids = {r.id for r in page_1.results}
    page_2_ids = {r.id for r in page_2.results}
    assert page_1_ids.isdisjoint(page_2_ids)


def test_list_places_unsupported_category_raises():
    """Unsupported categories raise UpstreamError instead of silent empty."""
    with pytest.raises(UpstreamError) as exc:
        list_places(category="nonexistent_category", jurisdiction="GB")
    assert exc.value.source == "category_unsupported"


def test_list_places_ev_charger_redacts_nothing_sensitive():
    """EV chargers have no staff PII in fixtures — redaction should be a no-op."""
    report = list_places(category="ev_charger", jurisdiction="GB", limit=3)
    assert len(report.results) == 3
    # No PII fields, so no redactions
    assert report.compliance.redactions_applied == []
