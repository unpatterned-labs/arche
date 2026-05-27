# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""restcountries.com integration — enrich jurisdiction profiles with live country metadata.

Provides phone calling codes, currencies, languages, capital cities, regions,
borders, and population data for any country. Results are cached in-memory
for the lifetime of the process.

This is a fallback enrichment layer for countries without full jurisdiction packs.
Countries WITH packs (e.g., Nigeria) use their pack data; restcountries fills gaps.

Usage:
    from arche.jurisdictions.restcountries import get_country, get_phone_code
    ng = get_country("NG")
    code = get_phone_code("NG")  # "+234"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

_log = logging.getLogger("arche.jurisdictions")

_API_BASE = "https://restcountries.com/v3.1"

# Vendored snapshot — 250 countries, fetched 2026-05-20. See
# ``arche/_data/README.md`` for source, refresh policy, and license.
_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "_data" / "restcountries-v3.1-snapshot.json"

# Fields requested at fetch time (kept under the 10-field API cap).
_FIELDS = "name,cca2,cca3,idd,currencies,languages,capital,region,subregion,borders"

# In-memory cache: country_code -> parsed dict. Populated lazily on first
# access from the vendored snapshot.
_cache: dict[str, dict[str, Any]] = {}
_snapshot_loaded = False


def _load_snapshot() -> None:
    """Populate `_cache` from the vendored restcountries snapshot.

    Idempotent — safe to call repeatedly. If the snapshot file is missing
    or unreadable, leaves `_cache` empty and logs a warning; live network
    fetching still works as a fallback.
    """
    global _snapshot_loaded
    if _snapshot_loaded:
        return
    _snapshot_loaded = True

    if not _SNAPSHOT_PATH.exists():
        _log.warning("restcountries snapshot not found at %s; will fall back to live API", _SNAPSHOT_PATH)
        return

    try:
        with _SNAPSHOT_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("failed to load restcountries snapshot: %s", exc)
        return

    if not isinstance(data, list):
        _log.warning("restcountries snapshot has unexpected shape: %s", type(data).__name__)
        return

    for entry in data:
        code = (entry.get("cca2") or "").upper()
        if code:
            _cache[code] = entry
    _log.debug("loaded %d countries from vendored restcountries snapshot", len(_cache))


def _fetch(url: str, timeout: int = 10) -> Any:
    """Fetch JSON from a URL with timeout.

    Respects the ``ARCHE_OFFLINE`` environment variable: when set to ``1``,
    ``true``, or ``yes``, all network calls are skipped silently.

    The vendored snapshot (loaded by ``_load_snapshot()``) covers the
    common case. ``_fetch`` is only invoked when a code is missing from
    the snapshot or the caller explicitly bypasses the cache.
    """
    import os

    if os.environ.get("ARCHE_OFFLINE", "").lower() in ("1", "true", "yes"):
        return None

    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        _log.warning("restcountries fetch failed: %s", e)
        return None


def get_country(country_code: str) -> dict[str, Any] | None:
    """Fetch country metadata from restcountries.com.

    Parameters
    ----------
    country_code:
        ISO 3166-1 alpha-2 (e.g., ``"NG"``, ``"GH"``, ``"KE"``).

    Returns
    -------
    dict or None
        Parsed country data, or None if the fetch failed.
        Result is cached after first successful fetch.
    """
    code = country_code.upper()
    _load_snapshot()
    if code in _cache:
        return _cache[code]

    data = _fetch(f"{_API_BASE}/alpha/{code}?fields={_FIELDS}")
    if not data:
        return None

    # API returns a list for alpha endpoint
    if isinstance(data, list):
        data = data[0] if data else None

    if data:
        _cache[code] = data
    return data


def get_phone_code(country_code: str) -> str | None:
    """Get the international dialling code for a country.

    Returns
    -------
    str or None
        E.g., ``"+234"`` for Nigeria, ``"+233"`` for Ghana.
    """
    data = get_country(country_code)
    if not data:
        return None

    idd = data.get("idd", {})
    root = idd.get("root", "")
    suffixes = idd.get("suffixes", [])
    if root and suffixes:
        return root + suffixes[0]
    return root or None


def get_currencies(country_code: str) -> list[dict[str, str]]:
    """Get currencies used in a country.

    Returns
    -------
    list[dict]
        E.g., ``[{"code": "NGN", "name": "Nigerian naira", "symbol": "₦"}]``
    """
    data = get_country(country_code)
    if not data:
        return []

    currencies = data.get("currencies", {})
    return [
        {"code": code, "name": info.get("name", ""), "symbol": info.get("symbol", "")}
        for code, info in currencies.items()
    ]


def get_languages(country_code: str) -> dict[str, str]:
    """Get official languages. Returns ``{"eng": "English", ...}``."""
    data = get_country(country_code)
    if not data:
        return {}
    return data.get("languages", {})


def get_borders(country_code: str) -> list[str]:
    """Get bordering country codes (alpha-3). E.g., ``["BEN", "CMR", "TCD", "NER"]``."""
    data = get_country(country_code)
    if not data:
        return []
    return data.get("borders", [])


def get_region(country_code: str) -> dict[str, str]:
    """Get region and subregion. E.g., ``{"region": "Africa", "subregion": "Western Africa"}``."""
    data = get_country(country_code)
    if not data:
        return {}
    return {
        "region": data.get("region", ""),
        "subregion": data.get("subregion", ""),
    }


def enrich_jurisdiction_profile(country_code: str) -> dict[str, Any]:
    """Build a lightweight jurisdiction profile from restcountries data.

    This is used for countries that don't have a full jurisdiction pack.
    It provides basic metadata for jurisdiction-aware extraction:
    phone code for normalization, currencies for money detection, etc.

    Returns
    -------
    dict
        Keys: country_code, country_name, phone_code, currencies, languages,
        capital, region, subregion, borders, population.
    """
    data = get_country(country_code)
    if not data:
        return {"country_code": country_code.upper(), "country_name": "Unknown"}

    name_data = data.get("name", {})
    idd = data.get("idd", {})
    root = idd.get("root", "")
    suffixes = idd.get("suffixes", [])
    phone_code = (root + suffixes[0]) if root and suffixes else root

    currencies = [
        {"code": code, "name": info.get("name", ""), "symbol": info.get("symbol", "")}
        for code, info in data.get("currencies", {}).items()
    ]

    return {
        "country_code": data.get("cca2", country_code.upper()),
        "country_name": name_data.get("common", ""),
        "official_name": name_data.get("official", ""),
        "phone_code": phone_code,
        "currencies": currencies,
        "languages": data.get("languages", {}),
        "capital": data.get("capital", []),
        "region": data.get("region", ""),
        "subregion": data.get("subregion", ""),
        "borders": data.get("borders", []),
        "population": data.get("population", 0),
        "flag": data.get("flag", ""),
    }


def preload_african_countries() -> dict[str, dict[str, Any]]:
    """Preload metadata for all African countries.

    Reads from the vendored snapshot when available (zero network calls);
    falls back to the live API otherwise.

    Returns
    -------
    dict
        country_code -> country metadata for all African nations.
    """
    _load_snapshot()

    if _cache:
        # Snapshot is populated; return the African subset.
        return {
            code: entry
            for code, entry in _cache.items()
            if entry.get("region") == "Africa"
        }

    # No snapshot available — fall back to live API.
    data = _fetch(f"{_API_BASE}/region/africa?fields={_FIELDS}")
    if not data or not isinstance(data, list):
        return {}

    result = {}
    for country in data:
        code = country.get("cca2", "")
        if code:
            _cache[code] = country
            result[code] = country
    return result


def clear_cache() -> None:
    """Clear the in-memory country cache (and forget that the snapshot was
    loaded, so the next access reloads it)."""
    global _snapshot_loaded
    _cache.clear()
    _snapshot_loaded = False
