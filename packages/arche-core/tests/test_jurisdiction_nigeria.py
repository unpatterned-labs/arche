"""Tests for the Nigeria jurisdiction pack."""

import pytest
from arche.jurisdictions import available_jurisdictions
from arche.jurisdictions import get_profile as get_profile_registry
from arche.jurisdictions.nigeria import (
    ADDRESS_NORMS,
    NAMING_CONVENTIONS,
    NDPA_COMPLIANCE,
    detect_ids,
    get_profile,
    identify_network,
    normalize_phone,
    validate_bvn,
    validate_nhis,
    validate_nin,
    validate_pvc,
    validate_tin,
)

# ── Profile tests ───────────────────────────────────────────────────────────


def test_profile_creation():
    profile = get_profile()
    assert profile.country_code == "NG"
    assert profile.country_name == "Nigeria"
    assert profile.version == "0.1.0"


def test_profile_has_id_patterns():
    profile = get_profile()
    assert len(profile.id_patterns) >= 4
    types = {p["id_type"] for p in profile.id_patterns}
    assert "NIN" in types
    assert "BVN" in types
    assert "TIN" in types
    assert "PVC" in types


def test_profile_has_phone_formats():
    profile = get_profile()
    assert len(profile.phone_formats) == 4
    operators = {p["operator"] for p in profile.phone_formats}
    assert operators == {"MTN", "Glo", "Airtel", "9mobile"}


def test_profile_has_naming_conventions():
    profile = get_profile()
    assert len(profile.naming_conventions) >= 3
    traditions = {c["tradition"] for c in profile.naming_conventions}
    assert "Yoruba" in traditions
    assert "Igbo" in traditions
    assert "Hausa" in traditions


def test_profile_has_compliance():
    profile = get_profile()
    assert "law" in profile.compliance_metadata
    assert "NDPA" in profile.compliance_metadata["law"]


def test_registry_get_ng():
    profile = get_profile_registry("NG")
    assert profile.country_code == "NG"


def test_registry_unavailable():
    with pytest.raises(ValueError, match="No jurisdiction pack"):
        get_profile_registry("XX")


def test_available_jurisdictions():
    avail = available_jurisdictions()
    assert "NG" in avail


# ── NIN validation ──────────────────────────────────────────────────────────


def test_validate_nin_valid():
    result = validate_nin("12345678901")
    assert result.is_valid
    assert result.id_type == "NIN"
    assert result.confidence >= 0.85


def test_validate_nin_too_short():
    result = validate_nin("1234567890")
    assert not result.is_valid


def test_validate_nin_too_long():
    result = validate_nin("123456789012")
    assert not result.is_valid


def test_validate_nin_not_digits():
    result = validate_nin("1234567890a")
    assert not result.is_valid


def test_validate_nin_bvn_prefix_rejected():
    """NIN validator should reject 22-prefixed values (those are BVNs)."""
    result = validate_nin("22100987654")
    assert not result.is_valid


# ── BVN validation ──────────────────────────────────────────────────────────


def test_validate_bvn_valid():
    result = validate_bvn("22100987654")
    assert result.is_valid
    assert result.id_type == "BVN"
    assert result.confidence >= 0.90


def test_validate_bvn_wrong_prefix():
    result = validate_bvn("12345678901")
    assert not result.is_valid


def test_validate_bvn_too_short():
    result = validate_bvn("2210098765")
    assert not result.is_valid


# ── TIN validation ──────────────────────────────────────────────────────────


def test_validate_tin_valid():
    result = validate_tin("1234567890")
    assert result.is_valid
    assert result.id_type == "TIN"


def test_validate_tin_too_long():
    result = validate_tin("12345678901")
    assert not result.is_valid


# ── PVC validation ──────────────────────────────────────────────────────────


def test_validate_pvc_valid():
    result = validate_pvc("90F5AB6224FA0018719")
    assert result.is_valid
    assert result.id_type == "PVC"


def test_validate_pvc_too_short():
    result = validate_pvc("ABC123")
    assert not result.is_valid


def test_validate_pvc_only_digits():
    result = validate_pvc("123456789012345678")
    assert not result.is_valid  # PVC must have letters and digits


# ── Phone normalization ─────────────────────────────────────────────────────


def test_normalize_phone_local():
    assert normalize_phone("0803 555 7890") == "+2348035557890"


def test_normalize_phone_international():
    assert normalize_phone("+234 803 555 7890") == "+2348035557890"


def test_normalize_phone_no_plus():
    assert normalize_phone("2348035557890") == "+2348035557890"


def test_normalize_phone_with_dashes():
    assert normalize_phone("0803-555-7890") == "+2348035557890"


def test_normalize_phone_invalid():
    assert normalize_phone("12345") is None


def test_normalize_phone_unknown_prefix():
    assert normalize_phone("0100 000 0000") is None


# ── Network identification ──────────────────────────────────────────────────


def test_identify_mtn():
    assert identify_network("0803 555 7890") == "MTN"


def test_identify_glo():
    assert identify_network("0805 555 7890") == "Glo"


def test_identify_airtel():
    assert identify_network("0802 555 7890") == "Airtel"


def test_identify_9mobile():
    assert identify_network("0809 555 7890") == "9mobile"


def test_identify_international():
    assert identify_network("+234 803 555 7890") == "MTN"


def test_identify_unknown():
    assert identify_network("0100 000 0000") is None


# ── ID detection in text ────────────────────────────────────────────────────


def test_detect_bvn_in_text():
    text = "Customer BVN is 22100987654, verified by NIBSS"
    results = detect_ids(text)
    bvn_results = [r for r in results if r.id_type == "BVN"]
    assert len(bvn_results) >= 1
    assert bvn_results[0].is_valid


def test_detect_nin_with_context():
    text = "His NIN number issued by NIMC is 12345678901"
    results = detect_ids(text)
    nin_results = [r for r in results if r.id_type == "NIN"]
    assert len(nin_results) >= 1
    # Context keyword "NIN" should boost confidence
    assert nin_results[0].confidence >= 0.90


def test_detect_tin_with_context():
    text = "FIRS tax identification number (TIN): 1234567890"
    results = detect_ids(text)
    tin_results = [r for r in results if r.id_type == "TIN"]
    assert len(tin_results) >= 1


# ── NDPA compliance data ────────────────────────────────────────────────────


def test_ndpa_has_key_requirements():
    assert "key_requirements" in NDPA_COMPLIANCE
    reqs = NDPA_COMPLIANCE["key_requirements"]
    assert "consent" in reqs
    assert "breach_notification" in reqs
    assert "dpia_required" in reqs


def test_ndpa_pii_categories():
    cats = NDPA_COMPLIANCE["pii_categories"]
    assert "NIN" in cats["high_sensitivity"]
    assert "BVN" in cats["high_sensitivity"]


# ── Address norms ───────────────────────────────────────────────────────────


def test_address_has_states():
    assert len(ADDRESS_NORMS["states"]) == 37  # 36 states + FCT


def test_address_has_major_cities():
    cities = ADDRESS_NORMS["major_cities"]
    assert "Lagos" in cities
    assert "Abuja" in cities
    assert "Kano" in cities


# ═══════════════════════════════════════════════════════════════════════════════
# HARDENING: Edge cases and cross-system integration
# ═══════════════════════════════════════════════════════════════════════════════


# ── NIN edge cases ──────────────────────────────────────────────────────────


def test_nin_with_spaces():
    result = validate_nin("123 4567 8901")
    assert result.is_valid


def test_nin_with_dashes():
    result = validate_nin("123-4567-8901")
    assert result.is_valid


def test_nin_empty():
    result = validate_nin("")
    assert not result.is_valid


def test_nin_all_zeros():
    result = validate_nin("00000000000")
    assert result.is_valid  # Valid format, structural only


def test_nin_all_nines():
    result = validate_nin("99999999999")
    assert result.is_valid


# ── BVN edge cases ──────────────────────────────────────────────────────────


def test_bvn_with_spaces():
    result = validate_bvn("22 100 987654")
    assert result.is_valid


def test_bvn_prefix_23_rejected():
    """Only 22 prefix is valid for BVN."""
    result = validate_bvn("23100987654")
    assert not result.is_valid


def test_bvn_empty():
    result = validate_bvn("")
    assert not result.is_valid


# ── TIN edge cases ──────────────────────────────────────────────────────────


def test_tin_with_dashes():
    result = validate_tin("12-345-67890")
    assert result.is_valid


def test_tin_9_digits():
    result = validate_tin("123456789")
    assert not result.is_valid


def test_tin_11_digits():
    result = validate_tin("12345678901")
    assert not result.is_valid


def test_tin_empty():
    result = validate_tin("")
    assert not result.is_valid


# ── PVC edge cases ──────────────────────────────────────────────────────────


def test_pvc_lowercase_valid():
    result = validate_pvc("90f5ab6224fa0018719")
    assert result.is_valid


def test_pvc_15_chars():
    result = validate_pvc("A1B2C3D4E5F6G7H")
    assert result.is_valid


def test_pvc_empty():
    result = validate_pvc("")
    assert not result.is_valid


# ── NHIS edge cases ─────────────────────────────────────────────────────────


def test_nhis_valid_8():
    result = validate_nhis("12345678")
    assert result.is_valid


def test_nhis_valid_15():
    result = validate_nhis("123456789012345")
    assert result.is_valid


def test_nhis_too_short():
    result = validate_nhis("1234567")
    assert not result.is_valid


def test_nhis_too_long():
    result = validate_nhis("1234567890123456")
    assert not result.is_valid


# ── Phone normalization edge cases ──────────────────────────────────────────


def test_normalize_phone_with_dots():
    assert normalize_phone("0803.555.7890") == "+2348035557890"


def test_normalize_phone_with_parens():
    assert normalize_phone("(0803) 555 7890") == "+2348035557890"


def test_normalize_phone_short_number():
    """Short numbers like emergency should return None."""
    assert normalize_phone("112") is None


def test_normalize_phone_landline():
    """Lagos landline — not a mobile prefix."""
    assert normalize_phone("01 270 0000") is None


def test_normalize_phone_all_operators():
    """Verify at least one prefix per operator normalizes correctly."""
    # MTN
    assert normalize_phone("0813 000 0000") == "+2348130000000"
    # Glo
    assert normalize_phone("0815 000 0000") == "+2348150000000"
    # Airtel
    assert normalize_phone("0901 000 0000") == "+2349010000000"
    # 9mobile
    assert normalize_phone("0818 000 0000") == "+2348180000000"


# ── Network identification edge cases ───────────────────────────────────────


def test_identify_network_stripped():
    """Number with no spaces."""
    assert identify_network("08035557890") == "MTN"


def test_identify_network_with_country_code():
    """+234 prefix."""
    assert identify_network("+2348055557890") == "Glo"


# ── Multiple IDs in one text ────────────────────────────────────────────────


def test_detect_nin_and_bvn_in_same_text():
    text = "NIN: 12345678901, BVN: 22100987654"
    results = detect_ids(text)
    types = {r.id_type for r in results}
    assert "NIN" in types
    assert "BVN" in types


def test_detect_no_ids_in_clean_text():
    text = "Hello, this is a normal sentence without any IDs."
    results = detect_ids(text)
    assert len(results) == 0


def test_detect_bvn_without_context():
    """BVN should still be found by 22-prefix even without context words."""
    text = "Number is 22100987654"
    results = detect_ids(text)
    bvn_results = [r for r in results if r.id_type == "BVN"]
    assert len(bvn_results) >= 1


# ── Resolution defaults ────────────────────────────────────────────────────


def test_resolution_defaults():
    from arche.jurisdictions.nigeria import RESOLUTION_DEFAULTS
    assert RESOLUTION_DEFAULTS["name_comparison"] == "jaro_winkler"
    assert RESOLUTION_DEFAULTS["use_cultural_naming"] is True
    assert "yoruba" in RESOLUTION_DEFAULTS["cultural_naming_traditions"]
    assert "igbo" in RESOLUTION_DEFAULTS["cultural_naming_traditions"]
    assert "hausa" in RESOLUTION_DEFAULTS["cultural_naming_traditions"]


# ── Profile completeness ───────────────────────────────────────────────────


def test_profile_serializable():
    """Profile should be Pydantic-serializable."""
    profile = get_profile()
    d = profile.model_dump()
    assert d["country_code"] == "NG"
    assert isinstance(d["id_patterns"], list)
    assert isinstance(d["compliance_metadata"], dict)


def test_profile_has_all_id_types():
    profile = get_profile()
    types = {p["id_type"] for p in profile.id_patterns}
    assert types >= {"NIN", "BVN", "TIN", "PVC", "NHIS", "NHF"}


# ── Naming conventions detail ──────────────────────────────────────────────


def test_naming_has_yoruba_prefixes():
    yoruba = next(c for c in NAMING_CONVENTIONS if c["tradition"] == "Yoruba")
    assert "Ade" in yoruba["common_prefixes"]
    assert len(yoruba["common_surnames"]) >= 5


def test_naming_has_igbo_prefixes():
    igbo = next(c for c in NAMING_CONVENTIONS if c["tradition"] == "Igbo")
    assert "Chi" in igbo["common_prefixes"]


def test_naming_has_hausa_conventions():
    hausa = next(c for c in NAMING_CONVENTIONS if c["tradition"] == "Hausa")
    assert len(hausa["conventions"]) >= 3


# ── NDPA depth ──────────────────────────────────────────────────────────────


def test_ndpa_lawful_bases():
    bases = NDPA_COMPLIANCE["key_requirements"]["lawful_basis"]
    assert "consent" in bases
    assert "legitimate_interests" in bases


def test_ndpa_data_subject_rights():
    rights = NDPA_COMPLIANCE["key_requirements"]["data_subject_rights"]
    assert "right_of_access" in rights
    assert "right_to_erasure" in rights


def test_ndpa_retention_limits():
    retention = NDPA_COMPLIANCE["retention_limits"]
    assert "financial_records" in retention
    assert "kyc_records" in retention


def test_ndpa_penalties():
    penalties = NDPA_COMPLIANCE["penalties"]
    assert "minor_violation" in penalties


# ── Cross-system: Nigeria pack + SDK pipeline ──────────────────────────────


def test_full_pipeline_nigerian_text():
    """End-to-end: Nigerian text → extract → resolve → governance."""
    from arche import resolve
    result = resolve(
        "Fatima Abdullahi, NIN 12345678901, phone 0803 555 7890, Lagos Nigeria",
        backend="regex",
    )
    assert result.entity_count >= 2


def test_governance_with_nigerian_evidence():
    """Governance module should load NDPA from Nigeria pack."""
    from arche.governance import assess_compliance
    evidence = [
        {"label": "nin", "text": "12345678901", "country_hint": "NG"},
        {"label": "bvn", "text": "22100987654", "country_hint": "NG"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    assert "NDPA" in report.law_name
    assert report.high_sensitivity_count >= 2
    assert report.dpia_required is False  # only 2 high, need 3 for DPIA
