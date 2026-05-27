# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""African address span detection, component parsing, and jurisdiction inference.

Per Stage 1 PRD §5 FR-ADDR-1..10. The v0.2.0a1 MVP focuses on Nigerian
and South African patterns — the two launch jurisdictions with the
most-distinctive address conventions. Kenya and Ghana are best-effort
through the shared city gazetteer; the full per-country parser for
KE/GH is grant-funded Stage 2 work.

What the v0.2 MVP handles:

- Number-prefixed street addresses ("7B Allen Avenue, Ikeja, Lagos")
- Plot-prefixed addresses ("Plot 14, Awolowo Road, Ikoyi, Lagos")
- Unit-prefixed addresses ("Unit 5B, 22 Riebeek Street, Cape Town")
- Box / P.O. Box addresses ("Box 1234, Sandton, Johannesburg, 2196")
- Landmark-anchored addresses ("behind the Total filling station,
  Madina Junction, Accra") — anchor extracted as a separate field
- Postal codes: 4-digit ZA, 6-digit NG (NIPOST), best-effort otherwise
- Jurisdiction inference via the gazetteer (~104 African cities)

What the v0.2 MVP does NOT handle (Stage 2 work):

- GERS ID matching (Overture Maps integration)
- Placekey emission
- libpostal-quality international structured addresses
- Code-mixed addresses (Pidgin / Swahili / Yoruba descriptors)
- Lat/lon estimation beyond gazetteer centroids

Public API::

    from arche.addr import parse_address, parse_addresses

    addr = parse_address("7B Allen Avenue, Ikeja, Lagos, Nigeria")
    addr.components.street       # "Allen Avenue"
    addr.components.city         # "Lagos"
    addr.country_inferred        # "NG"
    addr.country_confidence      # 0.95

    addrs = parse_addresses(
        "Delivery to 7B Allen Avenue, Ikeja, Lagos and to "
        "12 Long Street, Cape Town, 8001."
    )
    # -> list[Address] with both spans recovered
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data model (PRD §5.3)
# ---------------------------------------------------------------------------

@dataclass
class AddressComponents:
    """Per-component breakdown of a parsed address."""

    plot: str | None = None                # e.g., "Plot 14", "7B"
    street_number: str | None = None       # the bare number portion
    street: str | None = None              # "Allen Avenue", "Long Street"
    anchor: str | None = None              # landmark reference
    anchor_type: str | None = None         # commercial | religious | infrastructure
    neighborhood: str | None = None        # "Ikeja", "Sandton"
    area: str | None = None                # broader area within a city
    city: str | None = None                # "Lagos", "Cape Town"
    region: str | None = None              # state / province
    country: str | None = None             # ISO-3166-1 alpha-2
    postal_code: str | None = None         # 4-digit (ZA), 6-digit (NG), etc.


@dataclass
class Address:
    """A parsed address."""

    raw: str                                   # original substring
    span: tuple[int, int]                      # (start, end) in source
    components: AddressComponents = field(default_factory=AddressComponents)
    country_inferred: str | None = None        # ISO-3166-1 alpha-2
    country_confidence: float = 0.0
    confidence: float = 0.0
    gers_id: str | None = None                 # Stage 2
    placekey: str | None = None                # Stage 2
    lat_lon_estimate: tuple[float, float] | None = None


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Street-suffix tokens we recognise.  Order matters for the alternation.
_STREET_SUFFIXES = [
    "Avenue", "Street", "Road", "Drive", "Crescent", "Boulevard",
    "Lane", "Highway", "Close", "Way", "Court", "Square",
    "Ave", "St", "Rd", "Dr", "Blvd", "Ln", "Hwy", "Cl", "Sq",
]
_STREET_SUFFIX_RE = (
    r"(?:" + "|".join(_STREET_SUFFIXES) + r")\b"
)

# A street name: capitalized words followed by a suffix.
#   "Allen Avenue", "Long Street", "Mountain of Fire Crescent"
_STREET_NAME_RE = (
    r"(?P<street>"
    r"(?:[A-Z][\w'\-]+\s+){1,4}" + _STREET_SUFFIX_RE +
    r")"
)

# Plot / number prefixes
_PLOT_RE = r"(?P<plot>(?:Plot|Block|Unit|Suite|Flat|Apt|Apartment|No\.?)\s+\w+)"
_NUMBER_RE = r"(?P<number>\d{1,4}[A-Za-z]?)"

# Landmark anchor (informal African addresses)
_ANCHOR_PREPOSITIONS = [
    "behind", "near", "opposite", "beside", "next to", "in front of",
    "across from", "after", "before",
]
_ANCHOR_RE = (
    r"(?P<anchor>"
    r"\b(?:" + "|".join(_ANCHOR_PREPOSITIONS) + r")\s+"
    r"(?:the\s+)?"
    r"[A-Z][\w'\-]+(?:\s+[\w'\-]+){0,5}"  # 1-6 capitalised words
    r")"
)

# Anchor type heuristics (commercial / religious / infrastructure)
_COMMERCIAL_KEYWORDS = {"shop", "mall", "store", "supermarket", "filling station",
                        "gas station", "petrol", "market", "bank", "atm",
                        "hotel", "restaurant", "pharmacy"}
_RELIGIOUS_KEYWORDS = {"church", "mosque", "cathedral", "temple", "shrine",
                       "chapel", "parish"}
_INFRASTRUCTURE_KEYWORDS = {"junction", "roundabout", "bridge", "park",
                            "stadium", "hospital", "school", "university",
                            "airport", "station", "terminal"}

# Postal-code patterns per jurisdiction.
# Added GB in v0.2.0a2 (arche-places-0.1) per docs/ceo-plans/2026-05-24-places-resolver.md §4.6.
# UK postcodes follow the Royal Mail pattern: <AREA><DISTRICT> <SECTOR><UNIT>
#   AREA = 1-2 letters; DISTRICT = digit + optional letter/digit; SECTOR = digit; UNIT = 2 letters
# Example fulls: "SE1 7EH", "EC2A 4DP", "SW1A 1AA"
# Example partials (outward code only): "SW1", "SE1", "EC2A"
_POSTAL_PATTERNS = {
    "ZA": re.compile(r"\b(\d{4})\b"),           # South Africa 4-digit
    "NG": re.compile(r"\b(\d{6})\b"),           # Nigeria NIPOST 6-digit
    "KE": re.compile(r"\b(\d{5})\b"),           # Kenya 5-digit
    "GH": re.compile(r"\b([A-Z]{2}-\d{3}-\d{4})\b"),  # Ghana GhanaPost GPS
    "GB": re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b"),  # UK full
}

# UK partial / outward-code-only patterns (lower confidence).
# Used by infer_jurisdiction() when no full postcode is present.
_POSTAL_PARTIAL_PATTERNS = {
    "GB": re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b(?!\s*\d[A-Z]{2})"),
}

# The headline address-span regex.  Greedy across the typical
# "[plot,] [number] street_name, ..." structure.  Both ``plot`` and
# ``number`` are independently optional so the regex doesn't define
# the same named group twice (which Python's re module rejects).
#
# Tail segments are tightly typed so the regex doesn't run off into
# connector text ("Ship to X, Y, Z and copy to A, B, C"):
#
#   - A short capitalized phrase: 1-4 words, optional lowercase
#     "es" / "of" / "the" connectors (covers "Dar es Salaam", "Isle of Man")
#   - A postal-code-shaped string: 4-6 digits or GhanaPost GPS format
#
# Max 4 tail segments — a typical real address tail is at most:
# neighborhood, city, region, country (postal can replace any slot).
_TAIL_SEGMENT = (
    r"(?:"
    r"[A-Z][\w'\-]{1,25}"                           # 1st capitalized word
    r"(?:\s+(?:[A-Z][\w'\-]{1,25}|es|of|the)){0,3}" # 0-3 follow-on words
    r"|"
    r"\d{4,6}"                                       # 4-6 digit postal
    r"|"
    r"[A-Z]{2}-\d{3}-\d{4}"                          # GhanaPost GPS
    r")"
)
_ADDRESS_RE = re.compile(
    r"(?:" + _PLOT_RE + r"[\s,]+)?"
    r"(?:" + _NUMBER_RE + r"\s+)?"
    + _STREET_NAME_RE
    + r"(?P<tail>(?:\s*,\s*" + _TAIL_SEGMENT + r"){0,4})",
)

# A "Box NNN" pattern that doesn't require a street suffix.
_BOX_RE = re.compile(
    r"(?P<plot>(?:P\.?\s*O\.?\s*Box|Box)\s+\d+)"
    r"(?P<tail>(?:\s*,\s*[\w'\-\s]+){0,6})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_address(text: str) -> Address | None:
    """Parse the first address-like span found in ``text``.

    Returns ``None`` if no address pattern matched. For multiple
    addresses in one document, use :func:`parse_addresses`.
    """
    addresses = parse_addresses(text)
    return addresses[0] if addresses else None


def parse_addresses(text: str) -> list[Address]:
    """Detect and parse every address-like span in ``text``.

    Returns a list of :class:`Address` records sorted by start offset.
    Overlapping spans are deduplicated (longest wins).
    """
    candidates: list[tuple[tuple[int, int], Address]] = []

    # 1) Run the headline street-suffix regex
    for m in _ADDRESS_RE.finditer(text):
        addr = _build_address_from_match(m, text)
        if addr is not None:
            candidates.append((addr.span, addr))

    # 2) Run the Box-pattern regex
    for m in _BOX_RE.finditer(text):
        addr = _build_box_address_from_match(m, text)
        if addr is not None:
            candidates.append((addr.span, addr))

    if not candidates:
        return []

    # Deduplicate overlapping spans — keep the longest match per region
    candidates.sort(key=lambda c: (c[0][0], -(c[0][1] - c[0][0])))
    deduped: list[Address] = []
    last_end = -1
    for (start, end), addr in candidates:
        if start >= last_end:
            deduped.append(addr)
            last_end = end

    return sorted(deduped, key=lambda a: a.span[0])


# ---------------------------------------------------------------------------
# Internal: build Address from a regex match
# ---------------------------------------------------------------------------

def _build_address_from_match(m: re.Match[str], full_text: str) -> Address | None:
    """Convert a regex match into a structured Address record."""
    raw = m.group(0).strip()
    span = (m.start(), m.end())

    components = AddressComponents(
        plot=_clean(m.groupdict().get("plot")),
        street_number=_clean(m.groupdict().get("number")),
        street=_clean(m.groupdict().get("street")),
    )

    # Parse the trailing "city, region, country, postal" segment
    tail = m.groupdict().get("tail") or ""
    _parse_tail(tail, components)

    # Look for a landmark anchor in the text near the address span
    anchor_match = _find_anchor_near(full_text, span)
    if anchor_match is not None:
        components.anchor, components.anchor_type = anchor_match
        # Extend the span to include the anchor if it's adjacent
        start = min(span[0], _find_anchor_start(full_text, span))
        span = (start, span[1])
        raw = full_text[start:span[1]].strip()

    country, country_conf = _infer_country(components, full_text)
    components.country = country

    confidence = _score_address(components)

    return Address(
        raw=raw,
        span=span,
        components=components,
        country_inferred=country,
        country_confidence=country_conf,
        confidence=confidence,
    )


def _build_box_address_from_match(m: re.Match[str], full_text: str) -> Address | None:
    """Handle Box/PO Box addresses (no street suffix)."""
    raw = m.group(0).strip()
    span = (m.start(), m.end())

    components = AddressComponents(plot=_clean(m.groupdict().get("plot")))
    _parse_tail(m.groupdict().get("tail") or "", components)

    country, country_conf = _infer_country(components, full_text)
    components.country = country

    confidence = max(_score_address(components), 0.55)  # Box patterns are reliable

    return Address(
        raw=raw,
        span=span,
        components=components,
        country_inferred=country,
        country_confidence=country_conf,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Internal: tail parsing (city, region, country, postal)
# ---------------------------------------------------------------------------

def _parse_tail(tail: str, components: AddressComponents) -> None:
    """Split the comma-delimited tail into neighborhood/city/region/country/postal.

    Strategy: extract country and postal code first, then scan the
    remaining parts for cities **in the gazetteer**. When multiple
    parts hit the gazetteer (e.g., "Sandton, Johannesburg" or
    "Ikeja, Lagos"), prefer the **rightmost** match — that's the
    higher-level city in conventional African address ordering.
    Earlier parts that ALSO hit the gazetteer get demoted to
    neighborhood; later parts to region.
    """
    parts = [p.strip() for p in tail.split(",") if p.strip()]
    if not parts:
        return

    # Detect country (last part if it matches a known African country name)
    if parts and _looks_like_country(parts[-1]):
        components.country = _country_to_iso(parts[-1]) or parts[-1]
        parts = parts[:-1]

    # Detect postal code in the tail
    for i, part in enumerate(parts):
        if _looks_like_postal_code(part):
            components.postal_code = part
            parts.pop(i)
            break

    if not parts:
        return

    # Find ALL parts that match a known city; prefer the rightmost.
    gazetteer_hits: list[int] = [
        i for i, p in enumerate(parts) if _city_to_country(p) is not None
    ]

    if gazetteer_hits:
        # Rightmost gazetteer hit becomes the city.
        city_idx = gazetteer_hits[-1]
        components.city = parts[city_idx]
        # Earlier parts (incl. earlier gazetteer hits) are neighborhood / area.
        if city_idx > 0:
            components.neighborhood = parts[0]
            if city_idx > 1:
                components.area = ", ".join(parts[1:city_idx])
        # Later parts are region.
        if city_idx < len(parts) - 1:
            components.region = parts[city_idx + 1]
        return

    # No gazetteer match: fall back to heuristic positional parsing.
    if len(parts) == 1:
        components.city = parts[0]
    elif len(parts) >= 2:
        components.neighborhood = parts[0]
        components.city = parts[1]
        if len(parts) >= 3:
            components.region = parts[2]


# ---------------------------------------------------------------------------
# Internal: anchor (landmark) detection
# ---------------------------------------------------------------------------

def _find_anchor_near(text: str, address_span: tuple[int, int]) -> tuple[str, str] | None:
    """Find a landmark anchor (e.g., "behind the Total filling station")
    near the address span — typically immediately before."""
    window_start = max(0, address_span[0] - 80)
    window = text[window_start:address_span[0]]
    m = re.search(_ANCHOR_RE, window)
    if not m:
        return None
    anchor_text = m.group("anchor")
    return anchor_text, _classify_anchor(anchor_text)


def _find_anchor_start(text: str, address_span: tuple[int, int]) -> int:
    """Return the start offset of the anchor (if any) preceding ``address_span``."""
    window_start = max(0, address_span[0] - 80)
    window = text[window_start:address_span[0]]
    m = re.search(_ANCHOR_RE, window)
    if not m:
        return address_span[0]
    return window_start + m.start()


def _classify_anchor(anchor_text: str) -> str:
    """Classify the anchor as commercial / religious / infrastructure / other."""
    lower = anchor_text.lower()
    for kw in _COMMERCIAL_KEYWORDS:
        if kw in lower:
            return "commercial"
    for kw in _RELIGIOUS_KEYWORDS:
        if kw in lower:
            return "religious"
    for kw in _INFRASTRUCTURE_KEYWORDS:
        if kw in lower:
            return "infrastructure"
    return "other"


# ---------------------------------------------------------------------------
# Internal: country inference
# ---------------------------------------------------------------------------

# Map of African country names / aliases to ISO codes
_COUNTRY_ALIASES: dict[str, str] = {
    "nigeria": "NG", "south africa": "ZA", "kenya": "KE", "ghana": "GH",
    "ethiopia": "ET", "egypt": "EG", "morocco": "MA", "tanzania": "TZ",
    "uganda": "UG", "rwanda": "RW", "senegal": "SN", "cameroon": "CM",
    "cote d'ivoire": "CI", "ivory coast": "CI", "angola": "AO",
    "mozambique": "MZ", "zambia": "ZM", "zimbabwe": "ZW", "botswana": "BW",
    "namibia": "NA", "togo": "TG", "benin": "BJ", "burkina faso": "BF",
    "mali": "ML", "niger": "NE", "chad": "TD", "sudan": "SD",
    "south sudan": "SS", "somalia": "SO", "djibouti": "DJ", "eritrea": "ER",
}


def _looks_like_country(s: str) -> bool:
    return s.lower() in _COUNTRY_ALIASES


def _country_to_iso(s: str) -> str | None:
    return _COUNTRY_ALIASES.get(s.lower())


def _infer_country(components: AddressComponents, full_text: str) -> tuple[str | None, float]:
    """Three-level country inference per PRD §5.4.

    Level 1: explicit country name in the address (confidence >=0.95)
    Level 2: city-to-country lookup in the gazetteer (confidence ~0.85)
    Level 3: postal-code shape heuristic (confidence ~0.70)
    """
    # Level 1: explicit country
    if components.country and len(components.country) == 2:
        return components.country, 0.95

    # Level 2: gazetteer city lookup
    if components.city:
        country = _city_to_country(components.city)
        if country:
            return country, 0.85

    # Level 3: postal-code shape
    if components.postal_code:
        if re.fullmatch(r"\d{6}", components.postal_code):
            return "NG", 0.65
        if re.fullmatch(r"\d{5}", components.postal_code):
            return "KE", 0.65
        if re.fullmatch(r"\d{4}", components.postal_code):
            return "ZA", 0.65
        if re.fullmatch(r"[A-Z]{2}-\d{3}-\d{4}", components.postal_code):
            return "GH", 0.95  # Ghana GhanaPost GPS has very specific format
        if re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", components.postal_code):
            return "GB", 0.95  # UK postcode is very specific

    return None, 0.0


# ---------------------------------------------------------------------------
# Top-level jurisdiction inference (v0.2.0a2 — for PlaceResolver)
# ---------------------------------------------------------------------------

def infer_jurisdiction(text: str) -> tuple[str, float, str]:
    """Infer ISO 3166-1 alpha-2 country code from raw text.

    Distinct from :func:`_infer_country` which works on parsed AddressComponents.
    This scans raw text for any postcode/jurisdiction marker, useful when caller
    has a free-text query but no parsed Address yet.

    Returns ``(code, confidence, trigger)``:
        code        — ISO alpha-2 ("GB", "NG", "ZA", "KE", "GH", or "XX" if unknown)
        confidence  — 0.0 to 1.0
        trigger     — the substring that triggered the inference (for UX)

    Confidence ordering (high → low):
        explicit country name ........... 0.99
        full UK postcode ................ 0.95
        Ghana GhanaPost GPS ............. 0.95
        partial UK postcode ............. 0.85
        other country full postcode ..... 0.70
        no signal ....................... 0.00

    Examples::

        infer_jurisdiction("My mum lives near St. Thomas' Hospital in SW1")
        # -> ("GB", 0.85, "SW1")

        infer_jurisdiction("I'm at SE1 7EH right now")
        # -> ("GB", 0.95, "SE1 7EH")

        infer_jurisdiction("12B Adetokunbo Ademola Crescent, Wuse 2, Abuja, Nigeria")
        # -> ("NG", 0.99, "Nigeria")

        infer_jurisdiction("just some random text")
        # -> ("XX", 0.0, "")
    """
    # Level 1: explicit country name
    lower = text.lower()
    for alias, iso in _COUNTRY_ALIASES.items():
        # Word-boundary match so "mali" doesn't match inside "malingerer"
        if re.search(r"\b" + re.escape(alias) + r"\b", lower):
            return iso, 0.99, alias

    # Level 2: full postcodes (specific patterns first — GB and GH are unambiguous)
    for iso in ("GB", "GH"):  # check these first because they're highly specific
        pat = _POSTAL_PATTERNS.get(iso)
        if pat is None:
            continue
        m = pat.search(text)
        if m:
            return iso, 0.95, m.group(1)

    # Level 3: partial UK postcode (e.g., "SW1", "EC2A")
    partial_pat = _POSTAL_PARTIAL_PATTERNS.get("GB")
    if partial_pat is not None:
        m = partial_pat.search(text)
        if m:
            return "GB", 0.85, m.group(1)

    # Level 4: numeric-only postcodes (ambiguous — NG/KE/ZA share digit-only formats)
    # Lower confidence because a "12345" in random text isn't a strong signal.
    for iso in ("NG", "KE", "ZA"):
        pat = _POSTAL_PATTERNS.get(iso)
        if pat is None:
            continue
        m = pat.search(text)
        if m:
            return iso, 0.70, m.group(1)

    # No signal
    return "XX", 0.0, ""


# ---------------------------------------------------------------------------
# Internal: city + postal heuristics
# ---------------------------------------------------------------------------

def _city_to_country(name: str) -> str | None:
    """Look up a city in the bundled gazetteer to infer the country."""
    try:
        from arche.addr._gazetteer.cities import AFRICAN_CITIES
    except ImportError:
        return None
    normalized = name.strip().lower()
    for city in AFRICAN_CITIES:
        if city.name.lower() == normalized:
            return city.country
        if hasattr(city, "aliases"):
            for alias in city.aliases or []:
                if alias.lower() == normalized:
                    return city.country
    return None


def _looks_like_city(name: str) -> bool:
    """Best-effort check: capitalized 1-3 word phrase that might be a city."""
    if not name:
        return False
    # Heuristic: capitalized words, no digits
    if re.search(r"\d", name):
        return False
    words = name.split()
    if not all(w[0].isupper() for w in words if w):
        return False
    # Gazetteer membership is stronger than the heuristic
    if _city_to_country(name) is not None:
        return True
    # Otherwise: 1-3 capitalized words feels like a city candidate
    return 1 <= len(words) <= 3


_POSTAL_GENERIC_RE = re.compile(
    r"^(?:\d{4}|\d{5}|\d{6}|[A-Z]{2}-\d{3}-\d{4})$"
)


def _looks_like_postal_code(s: str) -> bool:
    return bool(_POSTAL_GENERIC_RE.match(s.strip()))


# ---------------------------------------------------------------------------
# Internal: scoring
# ---------------------------------------------------------------------------

def _score_address(components: AddressComponents) -> float:
    """Confidence score in [0, 1] for the parse quality.

    The more components recovered, the higher the score.
    """
    score = 0.0
    if components.street:
        score += 0.4
    if components.city:
        score += 0.2
    if components.country:
        score += 0.15
    if components.postal_code:
        score += 0.1
    if components.plot or components.street_number:
        score += 0.1
    if components.anchor:
        score += 0.05
    return min(score, 1.0)


def _clean(s: str | None) -> str | None:
    """Trim whitespace and collapse runs of spaces."""
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip() or None


__all__ = [
    "Address",
    "AddressComponents",
    "parse_address",
    "parse_addresses",
]
