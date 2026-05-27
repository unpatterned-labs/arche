"""Tests for the Kenya jurisdiction pack."""

from arche.jurisdictions import available_jurisdictions
from arche.jurisdictions import get_profile as get_profile_registry
from arche.jurisdictions.kenya import (
    ADDRESS_NORMS,
    DPA_COMPLIANCE,
    detect_ids,
    get_profile,
    identify_network,
    normalize_phone,
    validate_huduma_namba,
    validate_kra_pin,
    validate_national_id,
    validate_nhif,
)

# ── Profile tests ───────────────────────────────────────────────────────────


def test_profile_creation():
    profile = get_profile()
    assert profile.country_code == "KE"
    assert profile.country_name == "Kenya"
    assert profile.version == "0.1.0"


def test_profile_has_id_patterns():
    profile = get_profile()
    assert len(profile.id_patterns) >= 4
    types = {p["id_type"] for p in profile.id_patterns}
    assert "NATIONAL_ID" in types
    assert "HUDUMA" in types
    assert "KRA_PIN" in types
    assert "NHIF" in types


def test_profile_has_phone_formats():
    profile = get_profile()
    assert len(profile.phone_formats) == 3
    operators = {p["operator"] for p in profile.phone_formats}
    assert operators == {"Safaricom", "Airtel", "Telkom"}


def test_profile_has_naming_conventions():
    profile = get_profile()
    assert len(profile.naming_conventions) >= 4
    traditions = {c["tradition"] for c in profile.naming_conventions}
    assert "Kikuyu" in traditions
    assert "Luo" in traditions
    assert "Kalenjin" in traditions
    assert "Luhya" in traditions


def test_profile_has_compliance():
    profile = get_profile()
    assert "law" in profile.compliance_metadata
    assert "2019" in profile.compliance_metadata["law"]


def test_registry_get_ke():
    profile = get_profile_registry("KE")
    assert profile.country_code == "KE"


def test_ke_in_available_jurisdictions():
    avail = available_jurisdictions()
    assert "KE" in avail


# ── National ID validation ─────────────────────────────────────────────────


def test_validate_national_id_7_digits():
    result = validate_national_id("1234567")
    assert result.is_valid
    assert result.id_type == "NATIONAL_ID"
    assert result.confidence >= 0.85


def test_validate_national_id_8_digits():
    result = validate_national_id("12345678")
    assert result.is_valid
    assert result.metadata["format"] == "8-digit"


def test_validate_national_id_with_leading_zero():
    result = validate_national_id("01234567")
    assert result.is_valid


def test_validate_national_id_too_short():
    result = validate_national_id("123456")
    assert not result.is_valid


def test_validate_national_id_too_long():
    result = validate_national_id("123456789")
    assert not result.is_valid


def test_validate_national_id_not_digits():
    result = validate_national_id("1234567A")
    assert not result.is_valid


# ── KRA PIN validation ────────────────────────────────────────────────────


def test_validate_kra_pin_individual():
    result = validate_kra_pin("A123456789Z")
    assert result.is_valid
    assert result.id_type == "KRA_PIN"
    assert result.confidence >= 0.85
    assert result.metadata["entity_type"] == "individual"


def test_validate_kra_pin_company():
    result = validate_kra_pin("C987654321X")
    assert result.is_valid
    assert result.metadata["entity_type"] == "company"


def test_validate_kra_pin_partnership():
    result = validate_kra_pin("P111222333Y")
    assert result.is_valid
    assert result.metadata["entity_type"] == "partnership"


def test_validate_kra_pin_lowercase():
    result = validate_kra_pin("a123456789z")
    assert result.is_valid


def test_validate_kra_pin_wrong_format():
    result = validate_kra_pin("12345678901")
    assert not result.is_valid


def test_validate_kra_pin_too_few_digits():
    result = validate_kra_pin("A12345678Z")
    assert not result.is_valid


# ── Huduma Namba validation ────────────────────────────────────────────────


def test_validate_huduma_valid():
    result = validate_huduma_namba("HN12345678")
    assert result.is_valid
    assert result.id_type == "HUDUMA"


def test_validate_huduma_too_short():
    result = validate_huduma_namba("HN123")
    assert not result.is_valid


# ── NHIF validation ────────────────────────────────────────────────────────


def test_validate_nhif_valid():
    result = validate_nhif("12345678")
    assert result.is_valid
    assert result.id_type == "NHIF"


def test_validate_nhif_too_short():
    result = validate_nhif("12345")
    assert not result.is_valid


def test_validate_nhif_too_long():
    result = validate_nhif("12345678901")
    assert not result.is_valid


# ── Phone normalization ────────────────────────────────────────────────────


def test_normalize_phone_local_safaricom():
    assert normalize_phone("0722 123 456") == "+254722123456"


def test_normalize_phone_international():
    assert normalize_phone("+254 722 123 456") == "+254722123456"


def test_normalize_phone_no_plus():
    assert normalize_phone("254722123456") == "+254722123456"


def test_normalize_phone_with_dashes():
    assert normalize_phone("0722-123-456") == "+254722123456"


def test_normalize_phone_airtel():
    assert normalize_phone("0733 123 456") == "+254733123456"


def test_normalize_phone_telkom():
    assert normalize_phone("0770 123 456") == "+254770123456"


def test_normalize_phone_safaricom_new_prefix():
    """Safaricom 011x prefixes (newer allocations)."""
    assert normalize_phone("0110 123 456") == "+254110123456"


def test_normalize_phone_invalid():
    assert normalize_phone("12345") is None


def test_normalize_phone_unknown_prefix():
    assert normalize_phone("0400 000 000") is None


# ── Network identification ─────────────────────────────────────────────────


def test_identify_safaricom():
    assert identify_network("0722 123 456") == "Safaricom"


def test_identify_safaricom_0110():
    assert identify_network("0110 123 456") == "Safaricom"


def test_identify_airtel():
    assert identify_network("0733 123 456") == "Airtel"


def test_identify_telkom():
    assert identify_network("0770 123 456") == "Telkom"


def test_identify_international():
    assert identify_network("+254 722 123 456") == "Safaricom"


def test_identify_unknown():
    assert identify_network("0400 000 000") is None


# ── ID detection in text ───────────────────────────────────────────────────


def test_detect_kra_pin_in_text():
    text = "KRA PIN certificate shows A123456789Z for the taxpayer"
    results = detect_ids(text)
    kra_results = [r for r in results if r.id_type == "KRA_PIN"]
    assert len(kra_results) >= 1
    assert kra_results[0].is_valid


def test_detect_national_id_with_context():
    text = "National ID number on the identity card: 12345678"
    results = detect_ids(text)
    id_results = [r for r in results if r.id_type == "NATIONAL_ID"]
    assert len(id_results) >= 1
    assert id_results[0].confidence >= 0.90


# ── Compliance data ────────────────────────────────────────────────────────


def test_dpa_has_key_requirements():
    assert "key_requirements" in DPA_COMPLIANCE
    reqs = DPA_COMPLIANCE["key_requirements"]
    assert "consent" in reqs
    assert "breach_notification" in reqs
    assert "dpia_required" in reqs


def test_dpa_pii_categories():
    cats = DPA_COMPLIANCE["pii_categories"]
    assert "national_id" in cats["high_sensitivity"]
    assert "huduma_namba" in cats["high_sensitivity"]


# ── Address norms ──────────────────────────────────────────────────────────


def test_address_has_counties():
    assert len(ADDRESS_NORMS["counties"]) == 47


def test_address_has_major_cities():
    cities = ADDRESS_NORMS["major_cities"]
    assert "Nairobi" in cities
    assert "Mombasa" in cities
    assert "Kisumu" in cities
    assert "Nakuru" in cities
    assert "Eldoret" in cities
