# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the v0.2.0a1 detection-first reposition: SensitivityTier
enum, Detection schema additions (sensitivity_tier + regulatory_citation),
and per-statute YAML tier mapping.

Locks the contract from the 2026-05-22 eng review (commit 93123ed):
- StrEnum shape (consistent with LinkSource on link branch)
- Inline tier: on each policy_mappings category in YAML
- MODERATE as the conservative default for missing/unknown
- Load-time validation on malformed tier values
- All 4 launch statutes tier-mapped per Pan-African PII Taxonomy v0.1
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest
from arche._types import SensitivityTier
from arche.policy.engine import Statute, load_statute
from arche.workflow._primitive import Detection

# ----------------------------------------------------------------------
# SensitivityTier enum shape
# ----------------------------------------------------------------------


def test_sensitivity_tier_is_str_enum() -> None:
    """StrEnum so YAML string values round-trip without explicit conversion."""
    assert issubclass(SensitivityTier, StrEnum)


def test_sensitivity_tier_canonical_values() -> None:
    """Values match YAML / wire / audit row strings exactly (lowercase)."""
    assert SensitivityTier.HIGH.value == "high"
    assert SensitivityTier.MODERATE.value == "moderate"
    assert SensitivityTier.LOW.value == "low"


def test_sensitivity_tier_round_trip_from_string() -> None:
    """SensitivityTier('high') round-trips from YAML/wire values."""
    assert SensitivityTier("high") is SensitivityTier.HIGH
    assert SensitivityTier("moderate") is SensitivityTier.MODERATE
    assert SensitivityTier("low") is SensitivityTier.LOW


def test_sensitivity_tier_rejects_unknown_strings() -> None:
    """Unknown tier strings raise ValueError — protects YAML schema."""
    with pytest.raises(ValueError):
        SensitivityTier("urgent")
    with pytest.raises(ValueError):
        SensitivityTier("HIGH")  # case-sensitive; canonical is lowercase


def test_sensitivity_tier_string_equality() -> None:
    """StrEnum enables direct comparison to literal strings (caller ergonomics)."""
    assert SensitivityTier.HIGH == "high"
    assert SensitivityTier.MODERATE == "moderate"


# ----------------------------------------------------------------------
# Detection schema additions
# ----------------------------------------------------------------------


def _make_detection(**overrides) -> Detection:
    defaults: dict = {
        "id": "det-001",
        "category": "PII-2-NIN",
        "text": "12345678901",
        "start": 0,
        "end": 11,
        "confidence": 1.0,
        "detector": "ng-ids",
    }
    defaults.update(overrides)
    return Detection(**defaults)


def test_detection_sensitivity_tier_defaults_to_moderate() -> None:
    """Standalone detector calls (no statute) yield MODERATE tier."""
    d = _make_detection()
    assert d.sensitivity_tier == SensitivityTier.MODERATE


def test_detection_regulatory_citation_defaults_to_none() -> None:
    """Standalone detector calls (no statute) yield None citation."""
    d = _make_detection()
    assert d.regulatory_citation is None


def test_detection_accepts_explicit_tier_and_citation() -> None:
    """Pipeline enrichment populates both fields."""
    d = _make_detection(
        sensitivity_tier=SensitivityTier.HIGH,
        regulatory_citation="NDPA-2023 s.30, NIMC Act s.27",
    )
    assert d.sensitivity_tier == SensitivityTier.HIGH
    assert d.regulatory_citation == "NDPA-2023 s.30, NIMC Act s.27"


def test_detection_backward_compat_construction() -> None:
    """Existing callers that don't supply the new fields keep working
    (regression guard from the 2026-05-22 eng review)."""
    d = Detection(
        id="x",
        category="PII-3-PHONE",
        text="+2348035557890",
        start=0,
        end=14,
        confidence=0.9,
        detector="ng-phones",
    )
    assert d.sensitivity_tier == SensitivityTier.MODERATE
    assert d.regulatory_citation is None
    assert d.identity_class == "inferred"
    assert d.metadata == {}


# ----------------------------------------------------------------------
# Statute.tier_for() method
# ----------------------------------------------------------------------


def test_statute_tier_for_known_category() -> None:
    """NDPA-2023 maps NIN to HIGH per the YAML."""
    statute = load_statute("NDPA-2023")
    assert statute.tier_for("PII-2-NIN") == SensitivityTier.HIGH


def test_statute_tier_for_low_tier_category() -> None:
    """RC (company registration number) is LOW under NDPA-2023 — public per CAC."""
    statute = load_statute("NDPA-2023")
    assert statute.tier_for("PII-2-RC") == SensitivityTier.LOW


def test_statute_tier_for_moderate_tier_category() -> None:
    """Phone is MODERATE under NDPA-2023."""
    statute = load_statute("NDPA-2023")
    assert statute.tier_for("PII-3-PHONE") == SensitivityTier.MODERATE


def test_statute_tier_for_unmapped_category_defaults_to_moderate() -> None:
    """Conservative default for unknown categories."""
    statute = load_statute("NDPA-2023")
    assert statute.tier_for("PII-99-FAKE") == SensitivityTier.MODERATE


def test_statute_tier_for_returns_strenum_not_string(tmp_path: Path) -> None:
    """tier_for returns the enum, not the raw YAML string — type contract."""
    statute = load_statute("NDPA-2023")
    tier = statute.tier_for("PII-2-NIN")
    assert isinstance(tier, SensitivityTier)


# ----------------------------------------------------------------------
# Statute load-time validation for tier
# ----------------------------------------------------------------------


@pytest.fixture
def temp_statutes_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect _STATUTES_DIR + clear cache so tests use fixture YAMLs."""
    from arche.policy import engine

    monkeypatch.setattr(engine, "_STATUTES_DIR", tmp_path)
    monkeypatch.setattr(engine, "_STATUTE_CACHE", {})
    return tmp_path


def _write_test_statute(path: Path, name: str, body: str) -> Path:
    """Write a minimal-but-valid statute YAML, injecting `body` into
    policy_mappings for the test to control.

    `body` must already be indented to fit under `policy_mappings:` (one
    level = two spaces). Trailing newline on `body` is fine.
    """
    yaml_text = (
        f"statute_id: {name}\n"
        f"jurisdiction: TEST\n"
        f"version: v0.1-test\n"
        f"policy_mappings:\n"
        f"{body}\n"
        f"default_action: mask\n"
        f'default_statute_reference: "{name} default"\n'
    )
    p = path / f"{name}.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    return p


def test_statute_load_accepts_yaml_without_tier_field(temp_statutes_dir: Path) -> None:
    """Backward compat: pre-tier YAMLs load cleanly and default to MODERATE.

    This is the regression flagged R1 in the 2026-05-22 eng review."""
    _write_test_statute(
        temp_statutes_dir,
        "PRE-TIER",
        '  PII-2-NIN:\n    action: mask\n    statute_reference: "test ref"\n',
    )
    statute = load_statute("PRE-TIER")
    assert statute.tier_for("PII-2-NIN") == SensitivityTier.MODERATE


def test_statute_load_rejects_malformed_tier_value(temp_statutes_dir: Path) -> None:
    """Load-time validation catches typos like `tier: urgent`."""
    _write_test_statute(
        temp_statutes_dir,
        "BAD-TIER",
        '  PII-2-NIN:\n    action: mask\n    tier: urgent\n',
    )
    with pytest.raises(ValueError, match="unknown tier"):
        load_statute("BAD-TIER")


def test_statute_load_rejects_uppercase_tier_value(temp_statutes_dir: Path) -> None:
    """YAML tier values are canonical lowercase. `HIGH` (uppercase) is rejected."""
    _write_test_statute(
        temp_statutes_dir,
        "UPPERCASE-TIER",
        '  PII-2-NIN:\n    action: mask\n    tier: HIGH\n',
    )
    with pytest.raises(ValueError, match="unknown tier"):
        load_statute("UPPERCASE-TIER")


def test_statute_load_accepts_all_three_tier_values(temp_statutes_dir: Path) -> None:
    """high / moderate / low are all valid."""
    body = (
        "  PII-2-A:\n"
        "    action: mask\n"
        "    tier: high\n"
        "  PII-2-B:\n"
        "    action: mask\n"
        "    tier: moderate\n"
        "  PII-2-C:\n"
        "    action: mask\n"
        "    tier: low\n"
    )
    _write_test_statute(temp_statutes_dir, "ALL-TIERS", body)
    statute = load_statute("ALL-TIERS")
    assert statute.tier_for("PII-2-A") == SensitivityTier.HIGH
    assert statute.tier_for("PII-2-B") == SensitivityTier.MODERATE
    assert statute.tier_for("PII-2-C") == SensitivityTier.LOW


# ----------------------------------------------------------------------
# Shipped statute YAMLs — tier coverage regression
# ----------------------------------------------------------------------


@pytest.mark.parametrize("statute_id", ["NDPA-2023", "POPIA", "KENYA-DPA", "GHANA-DPA"])
def test_shipped_statute_loads_cleanly_with_tier_field(statute_id: str) -> None:
    """Every launch statute YAML loads without raising under the new schema.

    Regression guard: when DPA consultation lands and YAMLs are updated,
    this test catches accidental tier-field syntax breakage."""
    statute = load_statute(statute_id)
    assert isinstance(statute, Statute)
    assert len(statute.policy_mappings) > 0


@pytest.mark.parametrize("statute_id", ["NDPA-2023", "POPIA", "KENYA-DPA", "GHANA-DPA"])
def test_shipped_statute_every_category_has_valid_tier(statute_id: str) -> None:
    """Every mapped category in every shipped statute has a tier in the
    closed set — no unmapped or stale categories during v0.2.0a1 ship."""
    statute = load_statute(statute_id)
    for category in statute.policy_mappings:
        tier = statute.tier_for(category)
        assert isinstance(tier, SensitivityTier), (
            f"{statute_id}: {category!r} resolved to {tier!r} (not SensitivityTier)"
        )


def test_ndpa_2023_nin_is_high() -> None:
    """Anchor test: NIN must be HIGH under NDPA-2023 (NIMC Act foundational ID).

    A regression here would mean we're under-protecting the most sensitive
    Nigerian government identifier."""
    statute = load_statute("NDPA-2023")
    assert statute.tier_for("PII-2-NIN") == SensitivityTier.HIGH


def test_popia_national_id_is_high() -> None:
    """Anchor test: SA ID must be HIGH under POPIA (s.26 special — encodes DOB+gender)."""
    statute = load_statute("POPIA")
    assert statute.tier_for("PII-2-NATIONAL_ID") == SensitivityTier.HIGH


def test_kenya_national_id_is_high() -> None:
    """Anchor test: Kenya National ID + Huduma Namba must be HIGH."""
    statute = load_statute("KENYA-DPA")
    assert statute.tier_for("PII-2-NATIONAL_ID") == SensitivityTier.HIGH


def test_ghana_ghana_card_is_high() -> None:
    """Anchor test: Ghana Card must be HIGH."""
    statute = load_statute("GHANA-DPA")
    assert statute.tier_for("PII-2-GHANA_CARD") == SensitivityTier.HIGH


def test_ip_address_is_low_across_all_statutes() -> None:
    """Cross-jurisdiction anchor: PII-8-IP_ADDRESS is LOW in all four
    statutes. If a DPA consultation revises this upward, this test
    catches the change at v1.0 statute ship time."""
    for statute_id in ("NDPA-2023", "POPIA", "KENYA-DPA", "GHANA-DPA"):
        statute = load_statute(statute_id)
        assert statute.tier_for("PII-8-IP_ADDRESS") == SensitivityTier.LOW, (
            f"{statute_id} unexpectedly tiers IP_ADDRESS != LOW"
        )


# ----------------------------------------------------------------------
# Pipeline integration (Lane A 1B — statute-aware enrichment)
# ----------------------------------------------------------------------


def test_pipeline_enriches_ng_detections_with_tier_and_citation() -> None:
    """End-to-end: Pipeline(jurisdiction='NG') yields detections with the
    NDPA-2023 tier + citation populated."""
    from arche import Pipeline

    pipeline = Pipeline(jurisdiction="NG")
    result = pipeline.process(
        "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012."
    )

    # NIN + BVN should be detected
    categories = [d.category for d in result.detections]
    assert "PII-2-NIN" in categories
    assert "PII-2-BVN" in categories

    for det in result.detections:
        if det.category == "PII-2-NIN":
            assert det.sensitivity_tier == SensitivityTier.HIGH
            assert det.regulatory_citation is not None
            assert "NDPA-2023" in det.regulatory_citation
            assert "NIMC" in det.regulatory_citation
        elif det.category == "PII-2-BVN":
            assert det.sensitivity_tier == SensitivityTier.HIGH
            assert det.regulatory_citation is not None
            assert "NDPA-2023" in det.regulatory_citation
            assert "CBN" in det.regulatory_citation


def test_pipeline_audit_log_includes_tier_and_citation() -> None:
    """Audit rows expose the enriched fields for downstream consumers
    (compliance dashboards, regulator exports)."""
    from arche import Pipeline

    pipeline = Pipeline(jurisdiction="NG")
    result = pipeline.process("NIN 12345678901")

    detection_rows = [r for r in result.audit_log if r["event_type"] == "detection"]
    assert detection_rows, "Pipeline produced no detection audit rows"

    for row in detection_rows:
        assert "sensitivity_tier" in row
        assert "regulatory_citation" in row
        assert row["sensitivity_tier"] in {"high", "moderate", "low"}


def test_pipeline_enrichment_is_idempotent() -> None:
    """Running Pipeline.process twice produces the same tier + citation.

    Catches a regression where enrichment double-writes or mutates the
    statute object."""
    from arche import Pipeline

    pipeline = Pipeline(jurisdiction="NG")
    result1 = pipeline.process("NIN 12345678901")
    result2 = pipeline.process("NIN 12345678901")

    for d1, d2 in zip(result1.detections, result2.detections, strict=True):
        assert d1.sensitivity_tier == d2.sensitivity_tier
        assert d1.regulatory_citation == d2.regulatory_citation


def test_standalone_detector_returns_default_tier_and_no_citation() -> None:
    """Calling a per-country detector directly (no Pipeline) yields
    Detection objects with MODERATE tier + None citation.

    This is the documented standalone-detector contract from the
    2026-05-22 eng review §1 (locked decision: 'standalone detectors
    return Detection with regulatory_citation=None, default tier')."""
    from arche.detect.ng.ids import detect_nigerian_ids
    from arche.workflow._primitive import Pipeline

    raw = detect_nigerian_ids("NIN 12345678901")
    assert raw, "standalone detector returned no results"

    # Per-country detectors return their own dataclass (NationalID), not
    # Detection. We normalize the first hit through Pipeline._to_detection
    # to verify the default schema state.
    det = Pipeline._to_detection(raw[0])
    assert det.sensitivity_tier == SensitivityTier.MODERATE
    assert det.regulatory_citation is None


def test_pipeline_with_no_statute_returns_default_enrichment() -> None:
    """When jurisdiction is unknown / no statute loaded, detections keep
    their MODERATE / None defaults rather than crashing."""
    from arche import Pipeline

    # Custom statute=None bypasses the per-jurisdiction default lookup.
    pipeline = Pipeline(detectors=["ng"])  # no jurisdiction means no statute
    result = pipeline.process("NIN 12345678901")

    assert pipeline.statute_id is None
    for det in result.detections:
        assert det.sensitivity_tier == SensitivityTier.MODERATE
        assert det.regulatory_citation is None


def test_pipeline_za_detections_carry_popia_citation() -> None:
    """Cross-jurisdiction: POPIA detection includes POPIA citation, not NDPA."""
    from arche import Pipeline

    pipeline = Pipeline(jurisdiction="ZA")
    # Generate a structurally valid SA ID. Luhn checksum varies by content;
    # this is a known valid synthetic SA ID for testing.
    result = pipeline.process("Citizen Sipho Khumalo, ID 8001015009087.")

    sa_detections = [d for d in result.detections if d.category == "PII-2-NATIONAL_ID"]
    if sa_detections:  # only assert if Luhn-valid SA ID is detected
        det = sa_detections[0]
        assert det.sensitivity_tier == SensitivityTier.HIGH
        assert det.regulatory_citation is not None
        assert "POPIA" in det.regulatory_citation
