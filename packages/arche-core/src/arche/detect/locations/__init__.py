# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""African city / location detection via the bundled gazetteer.

Public surface per the 2026-05-22 detection-scope expansion::

    from arche.detect.locations import detect_locations

    detections = detect_locations(
        "Met Adesola in Lagos, then traveled to Nairobi via Cape Town."
    )
    # → [Detection(category='PII-4-LOCATION', text='Lagos', metadata={'country':'NG',...}),
    #    Detection(category='PII-4-LOCATION', text='Nairobi', ...),
    #    Detection(category='PII-4-LOCATION', text='Cape Town', ...)]

Cross-cutting (not country-specific). Public module name per the
v0.2.0a2 convention.

Returns :class:`~arche.workflow._primitive.Detection` objects with
``category="PII-4-LOCATION"``. The category was added to the
Pan-African PII Taxonomy in v0.1.1 (additive bump) — see
``datasets/pan-african-pii-taxonomy/v0.1.yaml`` (file internally
bumped to version 0.1.1).

Detection rules:

-   Lexicon-backed exact-match (case-insensitive) against the 104-city
    gazetteer (``arche.addr._gazetteer.cities.AFRICAN_CITIES``) plus
    each city's published aliases.
-   Word-boundary anchored — ``Lagos`` does NOT match inside ``Lagosian``.
-   Longest-match wins (``Cape Town`` matches before ``Cape`` would).
-   Each detection's ``metadata`` carries the ISO 3166-1 alpha-2
    country code, country name, and region from the gazetteer entry.

Distinct from ``PII-4-ADDRESS``: that category is for full street
addresses (parsed by ``arche.addr.parse_address``). PII-4-LOCATION is
for bare city or region mentions in prose.

The full gazetteer-load + regex-compile happens on the FIRST call to
:func:`detect_locations`. ``import arche.detect.locations`` itself is
cheap — no work at module load time, preserving the PRD NFR-PERF-1
<1s cold-import budget.
"""

from __future__ import annotations

import re
from threading import Lock

from arche.detect._base import _compile_lexicon, _lexicon_detect
from arche.workflow._primitive import Detection

# Lazy-init state. Compiled on first detect_locations() call.
_PATTERN: re.Pattern[str] | None = None
_TERM_TO_CITY: dict[str, dict[str, str]] = {}
_PATTERN_LOCK = Lock()


def _build_pattern() -> tuple[re.Pattern[str], dict[str, dict[str, str]]]:
    """Compile the gazetteer-backed location pattern + term → city metadata map.

    Each searchable term (city name or alias) maps to a metadata dict
    with country / country_name / region from the gazetteer entry.
    """
    from arche.addr._gazetteer.cities import AFRICAN_CITIES

    terms: list[str] = []
    term_to_city: dict[str, dict[str, str]] = {}
    for city in AFRICAN_CITIES:
        # City.name and each alias are independently searchable.
        # All map back to the same metadata bundle.
        meta = {
            "country": city.country,
            "country_name": city.country_name,
            "region": city.region,
            "canonical_name": city.name,
        }
        all_terms = [city.name, *city.aliases]
        for term in all_terms:
            if not term:
                continue
            terms.append(term)
            # Lowercase for case-insensitive lookup; the regex is also CI.
            term_to_city[term.lower()] = meta

    return _compile_lexicon(terms, case_insensitive=True), term_to_city


def _get_pattern_and_map() -> tuple[re.Pattern[str], dict[str, dict[str, str]]]:
    """Lazy-compile pattern + term-map. Thread-safe via double-checked lock."""
    global _PATTERN, _TERM_TO_CITY
    if _PATTERN is None:
        with _PATTERN_LOCK:
            if _PATTERN is None:
                _PATTERN, _TERM_TO_CITY = _build_pattern()
    return _PATTERN, _TERM_TO_CITY


def detect_locations(text: str, *, confidence: float = 0.9) -> list[Detection]:
    """Find African cities / locations in ``text`` via the bundled gazetteer.

    Args:
        text: Free-form input.
        confidence: Base confidence for matches. Default 0.9 — the
            gazetteer is curated (no synthetic generation) so matches
            are high-trust. Lower than 1.0 because some city names
            collide with common words (e.g. "Sun" if a city named Sun
            existed).

    Returns:
        List of :class:`Detection` objects with category
        ``PII-4-LOCATION``. Each carries ``metadata["country"]``,
        ``metadata["country_name"]``, ``metadata["region"]``,
        ``metadata["canonical_name"]`` (which may differ from the
        matched alias).
    """
    pattern, term_map = _get_pattern_and_map()

    def factory(match: re.Match[str]) -> dict[str, str]:
        # Look up the gazetteer entry by lowercase matched text.
        # Falls back to empty dict if the term map is missing the entry
        # (shouldn't happen but defensive).
        return dict(term_map.get(match.group(0).lower(), {}))

    return _lexicon_detect(
        text,
        pattern,
        category="PII-4-LOCATION",
        detector_name="rule:locations_gazetteer",
        identity_class="inferred",
        confidence=confidence,
        metadata_factory=factory,
    )


__all__ = ["detect_locations"]
