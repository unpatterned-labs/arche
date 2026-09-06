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
