"""Tests for the Ghana jurisdiction pack."""

from arche.jurisdictions import available_jurisdictions
from arche.jurisdictions import get_profile as get_profile_registry
from arche.jurisdictions.ghana import (
    ADDRESS_NORMS,
    DPA_COMPLIANCE,
    NAMING_CONVENTIONS,
    detect_ids,
    get_profile,
    identify_network,
    normalize_phone,
    validate_ghana_card,
    validate_nhis,
    validate_tin,
    validate_voter_id,
)

# ── Profile tests ───────────────────────────────────────────────────────────


def test_profile_creation():
    profile = get_profile()
    assert profile.country_code == "GH"
    assert profile.country_name == "Ghana"
    assert profile.version == "0.1.0"


def test_profile_has_id_patterns():
    profile = get_profile()
    assert len(profile.id_patterns) >= 4
    types = {p["id_type"] for p in profile.id_patterns}
    assert "GHANA_CARD" in types
    assert "TIN" in types
    assert "NHIS" in types
    assert "VOTER_ID" in types


def test_profile_has_phone_formats():
    profile = get_profile()
    assert len(profile.phone_formats) == 3
    operators = {p["operator"] for p in profile.phone_formats}
    assert operators == {"MTN", "Vodafone", "AirtelTigo"}


def test_profile_has_naming_conventions():
    profile = get_profile()
    assert len(profile.naming_conventions) >= 3
    traditions = {c["tradition"] for c in profile.naming_conventions}
    assert "Akan" in traditions
    assert "Ewe" in traditions
    assert "Ga" in traditions


def test_profile_has_compliance():
    profile = get_profile()
    assert "law" in profile.compliance_metadata
    assert "Act 843" in profile.compliance_metadata["law"]


def test_registry_get_gh():
    profile = get_profile_registry("GH")
    assert profile.country_code == "GH"


def test_gh_in_available_jurisdictions():
    avail = available_jurisdictions()
    assert "GH" in avail


# ── Ghana Card validation ──────────────────────────────────────────────────


def test_validate_ghana_card_valid():
    result = validate_ghana_card("GHA-123456789-0")
    assert result.is_valid
    assert result.id_type == "GHANA_CARD"
    assert result.confidence >= 0.90


def test_validate_ghana_card_no_hyphens():
    result = validate_ghana_card("GHA1234567890")
    assert result.is_valid


def test_validate_ghana_card_lowercase():
    result = validate_ghana_card("gha-123456789-0")
    assert result.is_valid


def test_validate_ghana_card_invalid_prefix():
    result = validate_ghana_card("NGN-123456789-0")
    assert not result.is_valid


def test_validate_ghana_card_too_few_digits():
    result = validate_ghana_card("GHA-12345678-0")
    assert not result.is_valid


def test_validate_ghana_card_no_check_digit():
    result = validate_ghana_card("GHA-123456789")
    assert not result.is_valid


# ── TIN validation ─────────────────────────────────────────────────────────


def test_validate_tin_individual():
    result = validate_tin("P0012345678")
    assert result.is_valid
    assert result.id_type == "TIN"
    assert result.metadata["entity_type"] == "individual"


def test_validate_tin_corporate():
    result = validate_tin("C0098765432")
    assert result.is_valid
    assert result.metadata["entity_type"] == "corporate"


def test_validate_tin_government():
    result = validate_tin("G0011111111")
    assert result.is_valid
    assert result.metadata["entity_type"] == "government"


def test_validate_tin_legacy_numeric():
    result = validate_tin("123456789")
    assert result.is_valid
    assert result.confidence < 0.80  # lower confidence for legacy format


def test_validate_tin_invalid():
    result = validate_tin("XYZ")
    assert not result.is_valid


# ── NHIS validation ────────────────────────────────────────────────────────


def test_validate_nhis_valid():
    result = validate_nhis("AB12345678")
    assert result.is_valid
    assert result.id_type == "NHIS"


def test_validate_nhis_too_short():
    result = validate_nhis("ABC")
    assert not result.is_valid


# ── Voter ID validation ───────────────────────────────────────────────────


def test_validate_voter_id_valid():
    result = validate_voter_id("V1234567890")
    assert result.is_valid
    assert result.id_type == "VOTER_ID"


def test_validate_voter_id_too_short():
    result = validate_voter_id("AB123")
    assert not result.is_valid


# ── Phone normalization ────────────────────────────────────────────────────


def test_normalize_phone_local_mtn():
    assert normalize_phone("024 123 4567") == "+233241234567"


def test_normalize_phone_international():
    assert normalize_phone("+233 24 123 4567") == "+233241234567"


def test_normalize_phone_no_plus():
    assert normalize_phone("233241234567") == "+233241234567"


def test_normalize_phone_with_dashes():
    assert normalize_phone("024-123-4567") == "+233241234567"


def test_normalize_phone_vodafone():
    assert normalize_phone("020 123 4567") == "+233201234567"


def test_normalize_phone_airteltigo():
    assert normalize_phone("026 123 4567") == "+233261234567"


def test_normalize_phone_invalid():
    assert normalize_phone("12345") is None


def test_normalize_phone_unknown_prefix():
    assert normalize_phone("030 123 4567") is None


# ── Network identification ─────────────────────────────────────────────────


def test_identify_mtn():
    assert identify_network("024 123 4567") == "MTN"


def test_identify_mtn_055():
    assert identify_network("055 123 4567") == "MTN"


def test_identify_vodafone():
    assert identify_network("020 123 4567") == "Vodafone"


def test_identify_airteltigo():
    assert identify_network("026 123 4567") == "AirtelTigo"


def test_identify_international():
    assert identify_network("+233 24 123 4567") == "MTN"


def test_identify_unknown():
    assert identify_network("030 123 4567") is None


# ── ID detection in text ───────────────────────────────────────────────────


def test_detect_ghana_card_in_text():
    text = "Applicant's Ghana Card is GHA-123456789-0, issued by NIA"
    results = detect_ids(text)
    card_results = [r for r in results if r.id_type == "GHANA_CARD"]
    assert len(card_results) >= 1
    assert card_results[0].is_valid


def test_detect_tin_with_context():
    text = "GRA tax identification (TIN): P0012345678"
    results = detect_ids(text)
    tin_results = [r for r in results if r.id_type == "TIN"]
    assert len(tin_results) >= 1


# ── Compliance data ────────────────────────────────────────────────────────


def test_dpa_has_key_requirements():
    assert "key_requirements" in DPA_COMPLIANCE
    reqs = DPA_COMPLIANCE["key_requirements"]
    assert "consent" in reqs
    assert "registration" in reqs


def test_dpa_pii_categories():
    cats = DPA_COMPLIANCE["pii_categories"]
    assert "ghana_card" in cats["high_sensitivity"]


# ── Address norms ──────────────────────────────────────────────────────────


def test_address_has_regions():
    assert len(ADDRESS_NORMS["regions"]) == 16


def test_address_has_major_cities():
    cities = ADDRESS_NORMS["major_cities"]
    assert "Accra" in cities
    assert "Kumasi" in cities
    assert "Tamale" in cities
    assert "Takoradi" in cities
    assert "Cape Coast" in cities


# ── Naming: Akan day-names ─────────────────────────────────────────────────


def test_akan_day_names_present():
    akan = [c for c in NAMING_CONVENTIONS if c["tradition"] == "Akan"][0]
    assert "day_names_male" in akan
    assert akan["day_names_male"]["Saturday"] == "Kwame"
    assert akan["day_names_female"]["Saturday"] == "Ama"
