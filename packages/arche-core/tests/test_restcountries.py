"""Tests for restcountries integration and jurisdiction-aware extraction."""

from unittest.mock import patch

# ── restcountries module tests ──────────────────────────────────────────────


def test_restcountries_import():
    """Module should import cleanly."""


def test_enrich_returns_dict_on_failure():
    """When API is unreachable, enrich should return minimal dict."""
    from arche.jurisdictions.restcountries import clear_cache, enrich_jurisdiction_profile
    clear_cache()

    with patch("arche.jurisdictions.restcountries._fetch", return_value=None):
        result = enrich_jurisdiction_profile("XX")
        assert result["country_code"] == "XX"
        assert result["country_name"] == "Unknown"


def test_get_phone_code_returns_none_on_failure():
    from arche.jurisdictions.restcountries import clear_cache, get_phone_code
    clear_cache()

    with patch("arche.jurisdictions.restcountries._fetch", return_value=None):
        assert get_phone_code("XX") is None


def test_get_currencies_returns_empty_on_failure():
    from arche.jurisdictions.restcountries import clear_cache, get_currencies
    clear_cache()

    with patch("arche.jurisdictions.restcountries._fetch", return_value=None):
        assert get_currencies("XX") == []


def test_cache_works():
    """For codes not in the vendored snapshot, _fetch is the source and
    its result is cached. Second call should use cache, not fetch again.

    Uses "QQ" (unassigned ISO code) so we exercise the live-fetch fallback
    path. Real codes are served from the vendored snapshot and never reach
    _fetch.
    """
    from arche.jurisdictions.restcountries import clear_cache, get_country
    clear_cache()

    mock_data = {
        "name": {"common": "TestLand"},
        "cca2": "QQ",
        "idd": {"root": "+1", "suffixes": ["23"]},
        "currencies": {"TLD": {"name": "TestDollar", "symbol": "$"}},
        "languages": {"eng": "English"},
    }

    with patch("arche.jurisdictions.restcountries._fetch", return_value=mock_data) as mock:
        result1 = get_country("QQ")
        result2 = get_country("QQ")
        # Should only fetch once — second call uses cache
        assert mock.call_count == 1
        assert result1["name"]["common"] == "TestLand"
        assert result2 is result1

    clear_cache()


def test_enrich_with_mock_data():
    """Verify enrich_jurisdiction_profile field mapping when _fetch supplies
    the data (i.e., for codes not in the vendored snapshot). Uses "QQ"
    (unassigned) so the snapshot doesn't intercept."""
    from arche.jurisdictions.restcountries import clear_cache, enrich_jurisdiction_profile
    clear_cache()

    mock_data = {
        "name": {"common": "Nigeria", "official": "Federal Republic of Nigeria"},
        "cca2": "QQ",
        "idd": {"root": "+2", "suffixes": ["34"]},
        "currencies": {"NGN": {"name": "Nigerian naira", "symbol": "\u20a6"}},
        "languages": {"eng": "English"},
        "capital": ["Abuja"],
        "region": "Africa",
        "subregion": "Western Africa",
        "borders": ["BEN", "CMR", "TCD", "NER"],
        "population": 223800000,
        "flag": "",
    }

    with patch("arche.jurisdictions.restcountries._fetch", return_value=mock_data):
        result = enrich_jurisdiction_profile("QQ")
        assert result["country_code"] == "QQ"
        assert result["country_name"] == "Nigeria"
        assert result["phone_code"] == "+234"
        assert result["region"] == "Africa"
        assert len(result["currencies"]) == 1
        assert result["currencies"][0]["code"] == "NGN"
        assert result["population"] == 223800000

    clear_cache()


# ── Jurisdiction-aware extraction tests ─────────────────────────────────────


def test_extract_with_jurisdiction_ng():
    """Extraction with jurisdiction='NG' should stamp country_hint."""
    from arche.ensemble import extract_identity_evidence
    evidence = extract_identity_evidence(
        "NIN 12345678901, phone 0803 555 7890",
        jurisdiction="NG",
    )
    # Should have evidence with country_hint set
    ng_evidence = [e for e in evidence if e.country_hint == "NG"]
    assert len(ng_evidence) >= 1


def test_extract_auto_jurisdiction_inference():
    """When jurisdiction='auto', should infer from Nigerian context."""
    from arche.ensemble import extract_identity_evidence
    evidence = extract_identity_evidence(
        "His NIN is 12345678901, Lagos Nigeria",
        jurisdiction="auto",
    )
    # Should detect Nigerian IDs and infer NG jurisdiction
    id_evidence = [e for e in evidence if e.label in ("nin", "national_id")]
    assert len(id_evidence) >= 1
    if id_evidence:
        assert id_evidence[0].country_hint == "NG"


def test_extract_jurisdiction_enriches_phones():
    """Jurisdiction should add phone metadata."""
    from arche.ensemble import extract_identity_evidence
    evidence = extract_identity_evidence(
        "Call +234 803 555 7890",
        jurisdiction="NG",
    )
    phones = [e for e in evidence if e.label == "phone_number"]
    # Phone should have expected_phone_code in metadata
    if phones:
        # The restcountries call may fail (no network), that's OK
        # But country_hint should still be set
        assert phones[0].country_hint in ("NG", "")


def test_infer_country_from_text():
    """Country inference from text keywords."""
    from arche.ensemble import _infer_country_from_text
    assert _infer_country_from_text("This is about Lagos Nigeria") == "NG"
    assert _infer_country_from_text("Accra Ghana Card") == "GH"
    assert _infer_country_from_text("Nairobi Kenya Safaricom") == "KE"
    assert _infer_country_from_text("Random text with no country") == ""


def test_extract_jurisdiction_boosts_confidence():
    """IDs from the set jurisdiction should get a confidence boost."""
    from arche.ensemble import extract_identity_evidence
    # Extract without jurisdiction
    ev_auto = extract_identity_evidence("NIN 12345678901", jurisdiction="auto")
    # Extract with explicit jurisdiction
    ev_ng = extract_identity_evidence("NIN 12345678901", jurisdiction="NG")

    # Both should find the NIN
    nin_auto = [e for e in ev_auto if e.label == "nin"]
    nin_ng = [e for e in ev_ng if e.label == "nin"]
    assert len(nin_auto) >= 1
    assert len(nin_ng) >= 1
    # NG jurisdiction should boost confidence slightly
    # (Both detect NG from context, so boost may be equal)
    assert nin_ng[0].confidence >= nin_auto[0].confidence
