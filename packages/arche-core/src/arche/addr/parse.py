# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

""" Address span detection, component parsing, and jurisdiction inference.
 The v0.2.0a1 MVP focuses on Nigerian
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
from pathlib import Path

from arche.addr import places as _places

# ---------------------------------------------------------------------------
# Data model (PRD §5.3)
# ---------------------------------------------------------------------------

@dataclass
class AddressComponents:
    """Per-component breakdown of a parsed address."""

    plot: str | None = None                # e.g., "Plot 14", "7B"
    unit: str | None = None                # "5th Floor", "Room 6", "Shop 12"
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
    "Place", "Terrace", "Gardens", "Grove", "Mews", "Walk", "Parade", "Row",
    "Parkway", "Trail", "Pike",
    "Ave", "St", "Rd", "Dr", "Blvd", "Ln", "Hwy", "Cl", "Sq", "Pkwy",
]
_STREET_SUFFIX_RE = (
    r"(?:" + "|".join(_STREET_SUFFIXES) + r")\b"
)

# A street name: capitalized words followed by a suffix.
#   "Allen Avenue", "Long Street", "Mountain of Fire Crescent"
# Not across a landmark word ("Ajala Drive Off Obodo Road" is two roads), nor
# across a building or estate ("Obodo Estate Ajala Avenue"), unless that word
# is the road's own name ("Estate Road", "Clinic Road").
_STREET_WORD_RE = (
    r"(?!(?:Off|Opposite|Opp|Near|Behind|Beside|Along|Adj|Adjacent|By)\b)"
    r"(?!(?:Estate|Plaza|Mall|Floor|Clinic|Building|House|Centre|Center)\s+(?!"
    + _STREET_SUFFIX_RE + r"))"
    r"(?:[A-Z][\w'\-]+|\d{1,3}(?:st|nd|rd|th|St|Nd|Rd|Th))"
)
# "Breakspear Road South", "Penn Avenue South": a direction closing the name.
_STREET_NAME_RE = (
    r"(?P<street>"
    r"(?:" + _STREET_WORD_RE + r"\s+){1,4}" + _STREET_SUFFIX_RE +
    r"(?:\s+(?:North|South|East|West)\b(?=\s*(?:,|$)))?"
    r")"
)

# Plot / number prefixes. "No" needs a digit after it, so "North" and "Nobel"
# are not read as "No" plus a number.
_PLOT_RE = (r"(?P<plot>\b(?i:(?:Plot|Block|Unit|Suite|Flat|Apt|Apartment)\s+|No\.?\s*(?=\d))"
            r"[\w/-]+)")
# A house number as written: "7", "4B", a range or pair ("62-80", "1/5"), or
# one carrying a layout code ("NX6/207", "CK-9", "KD 7"). A code joined by a
# space must be capitals, so "At 7" or "In 2" is not taken for one.
_NUMBER_RE = (r"(?P<number>(?<![\w/-])"
              r"(?:[A-Za-z]{1,3}\d{0,2}\s?[/-]\s?|[A-Z]{2,3}\s)?"
              r"\d{1,5}[A-Za-z]?(?:\s?[-/]\s?\d{1,4}[A-Za-z]?)?)")
# The word in front of a number that only says "a number follows".
_NUMBER_WORD_RE = re.compile(r"(?i)^(?:No\.?|Plot)\s*(?P<n>[A-Za-z]{0,3}-?\d[\w/-]*)$")
# A unit inside a building: a floor, room, suite, shop, flat or office.
_UNIT_RE = re.compile(
    r"(?i)\b(?:(?:\d{1,2}(?:st|nd|rd|th)|ground|first|second|third|fourth|fifth|top)"
    r"\s+floor\b|(?:floor|room|rm|suite|shop|flat|apt|apartment|unit|office)"
    r"\s*(?:no\.?\s*)?[A-Za-z]?\d[\w/-]*)")

# Landmark anchor (informal African addresses). The relation words and
# place-type keywords below are the built-in defaults; ``address_tokens.yaml``
# (merged by :func:`_merge_address_tokens`) extends them per region without a
# code change.
_ANCHOR_PREPOSITIONS = [
    "behind", "near", "opposite", "beside", "next to", "in front of",
    "across from", "after", "before",
    "in the vicinity of", "adjacent to", "next door to",
    "across the street from",
    # "in front of the" is deliberately absent: "in front of" is already here
    # and `_ANCHOR_ARTICLES` strips the article separately, so listing the
    # combined form adds a second rule that does the same job. Longest-first
    # sorting made it win, which meant two entries could both claim a match and
    # only one of them was load-bearing.
]
# Articles/determiners stripped between the relation word and the landmark.
_ANCHOR_ARTICLES = ["the"]

# Anchor type heuristics (commercial / religious / infrastructure).
_COMMERCIAL_KEYWORDS = {"shop", "mall", "store", "supermarket", "filling station",
                        "gas station", "petrol", "market", "bank", "atm",
                        "hotel", "restaurant", "pharmacy"}
_RELIGIOUS_KEYWORDS = {"church", "mosque", "cathedral", "temple", "shrine",
                       "chapel", "parish"}
_INFRASTRUCTURE_KEYWORDS = {"junction", "roundabout", "bridge", "park",
                            "stadium", "hospital", "school", "university",
                            "airport", "station", "terminal"}


def _merge_address_tokens() -> None:
    """Union contributor-supplied tokens from ``address_tokens.yaml`` into the
    built-in defaults, so local place types / relation words can be added
    without editing code. Best-effort: a missing or invalid file leaves the
    defaults intact, keeping the parser fully offline and dependency-light.
    """
    path = Path(__file__).resolve().parent / "address_tokens.yaml"
    try:
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        return
    for prep in data.get("anchor_prepositions") or []:
        if prep not in _ANCHOR_PREPOSITIONS:
            _ANCHOR_PREPOSITIONS.append(prep)
    for article in data.get("anchor_articles") or []:
        if article not in _ANCHOR_ARTICLES:
            _ANCHOR_ARTICLES.append(article)
    types = data.get("anchor_types") or {}
    _COMMERCIAL_KEYWORDS.update(types.get("commercial") or [])
    _RELIGIOUS_KEYWORDS.update(types.get("religious") or [])
    _INFRASTRUCTURE_KEYWORDS.update(types.get("infrastructure") or [])


_merge_address_tokens()

# Longest first so multi-word forms ("next to", "en face de") aren't shadowed
# by a shorter prefix during alternation / prefix stripping.
_ANCHOR_PREPOSITIONS.sort(key=len, reverse=True)
_ANCHOR_ARTICLES.sort(key=len, reverse=True)
# Every word that names a kind of landmark, in one alternation, longest first so
# "filling station" is tried before "station". Built AFTER
# `_merge_address_tokens()` so a contributor's `address_tokens.yaml` additions
# reach the lowercase branch below as well as `_classify_anchor`.
_ANCHOR_NOUN_RE = "|".join(
    re.escape(n) for n in sorted(
        _COMMERCIAL_KEYWORDS | _RELIGIOUS_KEYWORDS | _INFRASTRUCTURE_KEYWORDS,
        key=len, reverse=True)
)

# The landmark itself, in two forms.
#
# A capitalised phrase is a proper name and needs no further evidence: "behind
# the Total filling station" is an address because "Total" is a name.
#
# A lowercase phrase is the case this originally missed. Informal addresses are
# frequently written without capitals, and "behind the central mosque, Karfi,
# Kano State" is the example the project's own positioning uses to explain what
# a generic parser cannot do. It returned None, because the landmark had to
# begin with a capital and "central" does not. The religious vocabulary was
# already correct and simply never got consulted.
#
# The fix cannot be to drop that requirement. `_ANCHOR_PREPOSITIONS` includes
# `after` and `before`, which are ordinary English; admitting any lowercase
# words after them would read "after the meeting" as an address. So a lowercase
# landmark is accepted only when it ENDS in a word that names a kind of place,
# reusing the vocabulary `_classify_anchor` already keys on rather than
# inventing a second list that could drift from it.
_ANCHOR_LANDMARK_RE = (
    r"(?:"
    r"[A-Z][\w'\-]+(?:\s+[\w'\-]+){0,5}"  # 1-6 capitalised words
    r"|"
    r"(?:[a-z][\w'\-]*\s+){0,3}(?:" + _ANCHOR_NOUN_RE + r")\b(?!\s+[a-z])"
    r")"
)

_ANCHOR_RE = (
    r"(?P<anchor>"
    r"\b(?:" + "|".join(re.escape(p) for p in _ANCHOR_PREPOSITIONS) + r")\s+"
    r"(?:(?:" + "|".join(re.escape(a) for a in _ANCHOR_ARTICLES) + r")\s+)?"
    + _ANCHOR_LANDMARK_RE +
    r")"
)

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

# A full GB postcode as it appears inside an address tail: the Royal Mail
# shape plus the one non-geographic code (GIR 0AA), with or without the space,
# in either case. Case-insensitivity is scoped to the postcode itself so the
# tail's [A-Z] classes stay case-sensitive. Normalised by
# :func:`normalise_gb_postcode`.
_GB_POSTCODE = r"(?i:GIR\s*0AA|[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})"
_GB_POSTCODE_FULL_RE = re.compile(r"^" + _GB_POSTCODE + r"$")
_GB_POSTCODE_SUFFIX_RE = re.compile(r"^(?P<head>.*?)\s+(?P<pc>" + _GB_POSTCODE + r")$")


def normalise_gb_postcode(s: str) -> str | None:
    """``"nw16xe"`` -> ``"NW1 6XE"``; ``None`` when ``s`` is not a full GB postcode.

    The inward code is always the last three characters, so the canonical
    form is the compacted, upper-cased string with one space before them.
    """
    compact = re.sub(r"\s+", "", s or "").upper()
    if not _GB_POSTCODE_FULL_RE.match(compact):
        return None
    return compact[:-3] + " " + compact[-3:]


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
    # A town with its GB postcode and no comma between ("London NW1 6XE").
    # Tried FIRST and with lazy follow-on words, because the plain phrase
    # branch below would otherwise take "London NW1" (an outward code reads as
    # a capitalised word) and leave "6XE" behind, so the postcode was lost and
    # the city came back as "London NW1".
    r"[A-Z][\w'\-]{1,25}"
    r"(?:\s+(?:[A-Z][\w'\-]{1,25}|es|of|the)){0,3}?"
    r"\s+" + _GB_POSTCODE + r"\b"
    r"|"
    + _GB_POSTCODE + r"\b"                             # a GB postcode on its own
    r"|"
    r"[A-Z][\w'\-]{1,25}"                           # 1st capitalized word
    # 0-3 follow-on words; lists write "Nyeri town" as often as "Nyeri Town"
    r"(?:\s+(?:[A-Z][\w'\-]{1,25}|es|of|the|(?:town|estate|village|area)\b)){0,3}"
    r"|"
    r"\d{4,6}"                                       # 4-6 digit postal
    r"|"
    r"[A-Z]{2}-\d{3}-\d{4}"                          # GhanaPost GPS
    r")"
)
_ADDRESS_RE = re.compile(
    r"(?:" + _PLOT_RE + r"[\s,]+)?"
    r"(?:" + _NUMBER_RE + r"[\s,]+)?"
    + _STREET_NAME_RE
    + r"(?P<tail>(?:\s*,\s*" + _TAIL_SEGMENT + r"){0,4})",
)

# A "Box NNN" pattern that doesn't require a street suffix.
_BOX_RE = re.compile(
    r"(?P<plot>(?:P\.?\s*O\.?\s*Box|Box)\s+\d+)"
    r"(?P<tail>(?:\s*,\s*[\w'\-\s]+){0,6})",
    re.IGNORECASE,
)

# A landmark-only address: an anchor ("behind the Total filling station")
# followed by an optional locality tail. No street suffix, no postcode, no
# registry — the informal-address case that dominates in much of Africa.
_LANDMARK_RE = re.compile(
    _ANCHOR_RE + r"(?P<tail>(?:\s*,\s*" + _TAIL_SEGMENT + r"){0,4})",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_anchor(text: str) -> tuple[str, str] | None:
    """Extract a standalone landmark anchor and its type from free text.

    African addresses are frequently landmark-based ("behind the Total
    filling station, Madina, Accra") with no street, plot, or postcode.
    :func:`parse_address` only attaches an anchor when a street/box address
    is *also* present, so a landmark-only address parses to ``None`` and its
    anchor is lost. This helper recovers the anchor on its own, so callers
    (e.g. the resolver's address comparison) can use it as a first-class
    matching signal for the informal-address case that dominates in Africa.

    Returns ``(anchor_text, anchor_type)`` or ``None``. ``anchor_text``
    keeps its leading preposition, matching :attr:`AddressComponents.anchor`.
    """
    m = re.search(_ANCHOR_RE, text)
    if not m:
        return None
    anchor_text = m.group("anchor")
    return anchor_text, _classify_anchor(anchor_text)


def extract_unit(text: str) -> str | None:
    """The unit inside a building ("5th Floor", "Room 6", "Shop 12"), if any.

    Like :func:`extract_anchor`, for text the street parser finds nothing in:
    "Sarit Centre 4th floor" has no street, so it parses to ``None``.
    """
    m = _UNIT_RE.search(text)
    return _clean(m.group(0)) if m else None


# Where a landmark begins inside a part: the relation words, plus the short
# forms provider lists use ("Opp", "adj"). The words that are also ordinary
# English ("by", "off", "of", "after", "before") count only at the start of a
# part. "along" is not one: "along Kanyiri Road" says the place is on that road.
_LANDMARK_WORD_RE = re.compile(
    r"(?i)\b(?:" + "|".join(
        re.escape(p) for p in _ANCHOR_PREPOSITIONS if p not in ("after", "before"))
    + r"|opp|adj|inside|along)\b\.?")
_ALONG_RE = re.compile(r"(?i)^along\s+(?P<road>.+)$")
# Words that say what a place is, not which part of it ("Temanu town").
_PLACE_WORDS = {"town", "city", "municipality", "township"}
_LANDMARK_START_RE = re.compile(r"(?i)^(?:by|off|of|after|before)\b")
# A part that names a road or a building rather than a place.
_NOT_A_PLACE_RE = re.compile(
    r"(?i)\b(?:" + "|".join(_STREET_SUFFIXES) + "|" + _ANCHOR_NOUN_RE
    + r"|building|plaza|complex|centre|center|tower|round\s*about|bypass|expressway"
    r"|b/stop|bus\s*stop|stop|stage|garage)\b")
_LEADING_COUNT_RE = re.compile(r"^\s*\d{1,2}\)\.?\s*")
_BOX_PART_RE = re.compile(r"(?i)^(?:p\.?\s*o\.?\s*box|box|p\.?\s*m\.?\s*b)\b")


# Words that only qualify a place ("New Legon", "Old Cairo", "Nairobi West");
# a place name is never split to leave one of these on its own.
_QUALIFIERS = {"new", "old", "north", "south", "east", "west", "upper", "lower",
               "central", "greater", "little", "big", "town", "city", "municipality",
               "township", "state", "region", "county", "province", "district",
               "division", "lga", "sub county", "subcounty"}
# Words that make a place name with the word before them ("Kanyiri Estate",
# "Obodo Area", "Ajala Village", "Temanu Community 1"); a part holding one is
# one place, not two.
_PLACE_NOUN_RE = re.compile(
    r"(?i)\b(?:estate|area|village|quarters?|community|comm|location|layout|"
    r"extension|phase|zone|camp|bus[\s-]?stop|b/stop|stop|stage|junction|house|"
    r"plaza|building|centre|center|market|residential|city|development|annex)\b")


def _split_places(part: str) -> list[str]:
    """A part naming two places with no comma between, as two parts.

    "Kanyiri Ibadan" and "Obodo Ridge Accra" run smaller to larger and give
    ``["Kanyiri", "Ibadan"]``; "Kumasi Kanyiri" and "Tamale Obodo" run larger
    to smaller and are put the same way round, ``["Kanyiri", "Kumasi"]``, so
    the town is last either way. The split is where the place list knows one
    side as a town (or both, the larger deciding the order), in a country it
    covers in full (:func:`arche.addr.places.focus_rank`): elsewhere it lacks
    small places, so "Moss Side" would split on a Side it knows from Turkey.
    A part the list knows whole ("Benin City", "Port Harcourt"), a postcode,
    or a part holding a place noun ("Kanyiri Estate") is returned as it is.
    """
    words = part.split()
    if (len(words) < 2 or len(words) > 10 or _places.lookup(part) is not None
            or _PLACE_NOUN_RE.search(part) or normalise_gb_postcode(part)
            or _looks_like_postal_code(part)):
        return [part]
    best: tuple | None = None
    for k in range(1, len(words)):
        head, tail = " ".join(words[:k]), " ".join(words[k:])
        if _places.fold(head) in _QUALIFIERS or _places.fold(tail) in _QUALIFIERS:
            continue
        rh, rt = _places.focus_rank(head), _places.focus_rank(tail)
        # A town, not a village: villages share names with ordinary words
        # ("Side", "State"), and a village alone is too weak to split on.
        if max(rh, rt) < 3:
            continue
        score = ((rh > 0) + (rt > 0), max(rh, rt), len(head if rh >= rt else tail))
        if best is None or score > best[0]:
            best = (score, head, tail, rh, rt)
    if best is None:
        return [part]
    _, head, tail, rh, rt = best
    return [head, tail] if rt >= rh else [tail, head]


def _order_places(parts: list[str]) -> list[str]:
    """The place parts, split where two share a part, smallest first.

    Addresses usually name places smallest first, so the town is last. When the
    first part is a town that outranks every later one ("Kumasi, Ahodwo"), the
    address runs the other way, and the town is moved to the end. Every later
    part must be a place the list knows; an unknown one keeps the order.
    """
    out = [p for part in parts for p in _split_places(part)]
    if len(out) >= 2:
        first = _places.focus_rank(out[0])
        # Every later part must be known, and smaller: "Ashgrove, Temanu" with
        # Temanu unknown keeps its order, whatever Ashgrove is elsewhere.
        if first >= 3 and all(0 < _places.focus_rank(p) < first for p in out[1:]) \
                and not any(_places.lookup(p) and _places.lookup(p).region for p in out[1:]):
            out = out[1:] + out[:1]
    return out


def parse_locality(text: str) -> AddressComponents | None:
    """The places in an address with no street: "Tamale near Obodo Filling Station".

    For text :func:`parse_address` finds no street in, as
    :func:`extract_anchor` is. The text is split at commas, newlines and
    dashes; landmark phrases ("near ...", "Opp ..."), units, numbers, P.O.
    boxes, and parts naming a road or a building are set aside. Of the parts
    left, the last is the city unless it names its own level ("Lagos State"),
    when it is the region and the one before it the city; parts before the
    city are neighbourhood and area: in "Ashgrove, Temanu" the city is Temanu,
    whether or not either is in the gazetteer. The one exception is an address
    that runs larger to smaller: when it begins with a town the gazetteer knows
    and no later part is one ("Kumasi Kanyiri Obodo"), that town is the city
    and the rest are neighbourhood and area. "along" names the road the place
    is on ("Ashgrove along Kanyiri Road"), not a landmark.

    Returns ``None`` when no place is left, or when what is left is too long
    to be a place name (more than four words).
    """
    unit = extract_unit(text)
    rest = _UNIT_RE.sub(" ", text) if unit else text
    rest, code, state = _closing_code(rest)
    parts: list[str] = []
    anchor: str | None = None
    street: str | None = None
    for raw in re.split(r"[,;\n]|\s-\s|(?<=\w)-\s", _LEADING_COUNT_RE.sub("", rest)):
        part = raw.strip(" .")
        if not part:
            continue
        m = _LANDMARK_WORD_RE.search(part)
        if _LANDMARK_START_RE.match(part):
            m_start = 0
        elif m is not None:
            m_start = m.start()
        else:
            m_start = None
        if m_start is not None:
            phrase = _clean(part[m_start:]) or ""
            along = _ALONG_RE.match(phrase)
            if (along and street is None
                    and re.search(r"(?i)\b" + _STREET_SUFFIX_RE, along.group("road"))):
                street = along.group("road")
            else:
                anchor = anchor or phrase
            part = part[:m_start].strip(" .")
        if (not part or part[0].isdigit() or _NUMBER_WORD_RE.match(part)
                or _BOX_PART_RE.match(part)
                or (_NOT_A_PLACE_RE.search(part) and not _AREA_END_RE.match(part))):
            continue
        parts.append(part)
    if not parts:
        if street is None:
            return None
        return AddressComponents(street=street, anchor=anchor, unit=unit,
                                 anchor_type=_classify_anchor(anchor) if anchor else None)
    components = AddressComponents(street=street, anchor=anchor, unit=unit,
                                   postal_code=code, region=state)
    if code is None and len(parts) >= 2 and _looks_like_postal_code(parts[-1]):
        components.postal_code = parts.pop()
    if len(parts) >= 2 and _REGION_PART_RE.search(parts[-1]):
        components.region = parts.pop()
    parts = _order_places(parts)
    city = parts.pop()
    if len(city.split()) > 4:
        return None
    components.city = _clean(city)
    if parts:
        components.neighborhood = _clean(parts[0])
        if len(parts) > 1:
            components.area = _clean(", ".join(parts[1:]))
    if components.anchor:
        components.anchor_type = _classify_anchor(components.anchor)
    return components


def normalize_landmark(text: str) -> str:
    """Strip the leading relation word + article from a landmark descriptor.

    "behind the Total filling station" and "nyuma ya Total filling station"
    both reduce to "Total filling station", so a landmark compares the same
    across the code-mixed relation words used in African addresses. Shared by
    the parser and the resolver's address comparison so they use one vocabulary.
    """
    s = text.strip()
    low = s.lower()
    for prep in _ANCHOR_PREPOSITIONS:  # longest-first (sorted at module load)
        if low.startswith(prep.lower() + " "):
            s = s[len(prep):].lstrip()
            low = s.lower()
            break
    for article in _ANCHOR_ARTICLES:  # longest-first
        if low.startswith(article.lower() + " "):
            s = s[len(article):].lstrip()
            break
    return s


def parse_address(text: str) -> Address | None:
    """Parse the first address-like span found in ``text``.

    Returns ``None`` if no address pattern matched. For multiple
    addresses in one document, use :func:`parse_addresses`.
    """
    addresses = parse_addresses(text)
    return addresses[0] if addresses else None


# The fields read from the text, as opposed to inferred (country, anchor_type).
_TEXT_FIELDS = ("plot", "unit", "street_number", "street", "anchor", "neighborhood",
                "area", "city", "region", "postal_code")


_CODE_BEFORE_NUMBER_RE = re.compile(r"\b[A-Za-z]{1,3}(?=\s?\d)")
_NOT_CODES = {"no", "at", "in", "on", "by", "of", "to", "km", "rd", "st", "nd", "th",
              "box", "pmb", "rm", "apt", "plot", "flat", "shop", "room", "unit"}


# A road written without capitals in an otherwise mixed-case address: a whole
# comma part ("Kanyiri road, Temanu town"), or one after "along". Only the full
# street words, and only in a short single line that does not read as prose.
_LOWER_ROAD_RE = re.compile(
    r"(?:(?<=^)|(?<=,)|(?<=, )|(?<=\balong )|(?<=\bAlong ))"
    r"(?:\d{1,4}[A-Za-z]?\s+)?"
    r"(?:(?!(?:of|off|opp|opposite|near|behind|by|along|adj|the|a|an|and)\b)"
    r"[A-Za-z][\w'\-]*\s+){1,3}"
    r"(?:road|street|avenue|drive|crescent|lane|close|way|highway|boulevard)\b")
_PROSE_RE = re.compile(
    r"(?i)\b(?:is|was|are|were|be|been|i|we|you|he|she|they|it|my|our|your|his|their|"
    r"will|would|has|have|had|from|with|that|this|these|please|when|then|who|which)\b")


def _recase(text: str) -> str:
    """All-capitals or all-lowercase text with each word capitalised.

    The patterns read case: a street or a town is a run of capitalised words,
    and a layout code ("KD 7") is capitals. Provider lists are often written
    all in capitals ("6 AJALA STREET, TEMANU") or all in lowercase, where
    case says nothing; this gives the patterns the case they expect. Only
    ASCII letters change, so every offset into the text stays the same.
    """
    if text == text.upper() or text == text.lower():
        cased = re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), text)
        # A short code before a number stays in capitals ("KD 7", "SX5/311"),
        # but not a word ("No 7", "At 7", "KM 3").
        return _CODE_BEFORE_NUMBER_RE.sub(
            lambda m: m.group(0) if m.group(0).lower() in _NOT_CODES
            else m.group(0).upper(), cased)
    if "\n" not in text and len(text) <= 120 and not _PROSE_RE.search(text):
        return _LOWER_ROAD_RE.sub(
            lambda m: re.sub(r"[A-Za-z]+", lambda w: w.group(0)[:1].upper() + w.group(0)[1:],
                             m.group(0)), text)
    return text


def _restore_case(addr: Address, cased: str, text: str) -> None:
    """Put each component back as written, where it is a slice of the text."""
    addr.raw = text[addr.span[0]:addr.span[1]].strip()
    start = max(0, addr.span[0] - 80)
    for name in _TEXT_FIELDS:
        value = getattr(addr.components, name)
        if value:
            i = cased.find(value, start)
            if i >= 0:
                setattr(addr.components, name, text[i:i + len(value)])


def parse_addresses(text: str) -> list[Address]:
    """Detect and parse every address-like span in ``text``.

    Returns a list of :class:`Address` records sorted by start offset.
    Overlapping spans are deduplicated (longest wins). Text written all in
    capitals or all in lowercase is read as if each word were capitalised;
    the components come back as written.
    """
    cased = _recase(text)
    found = _parse_addresses(cased)
    if cased != text:
        for addr in found:
            _restore_case(addr, cased, text)
    return found


def _parse_addresses(text: str) -> list[Address]:
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

    # 3) Run the landmark-anchor regex (informal addresses with no street
    #    suffix, e.g. "behind the Total filling station, Madina, Accra").
    #    Overlaps with a street/box match are dropped by the dedup below, so a
    #    street address that already absorbed its anchor still wins.
    for m in _LANDMARK_RE.finditer(text):
        addr = _build_landmark_address_from_match(m, text)
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
    # "No 7" and "Plot 7" carry a house number of 7; "Unit 4" and "Suite 4" a unit.
    if components.plot is not None:
        bare = _NUMBER_WORD_RE.match(components.plot)
        if bare is not None and components.street_number is None:
            components.street_number = bare.group("n")
        elif re.match(r"(?i)(?:unit|suite|flat|apt|apartment)\b", components.plot):
            components.unit = components.plot
    if components.unit is None:
        components.unit = _find_unit_near(full_text, span)

    # Parse the trailing "city, region, country, postal" segment, past any
    # landmark, P.O. box or second road between the street and the town.
    tail, tail_anchor, code, state = _tail_after(full_text, m.end("street"))
    _parse_tail(tail, components)
    if code is not None:
        components.postal_code = code
        # Before a postcode the last part is the town, if it is one ("Stretford,
        # Manchester"); a county there is not ("Chesterfield, Derbyshire").
        parts = [p.strip() for p in tail.split(",") if p.strip()]
        if len(parts) >= 2 and state is None and _places.town_rank(parts[-1]) >= 3 \
                and parts[-1].casefold() not in _UK_COUNTIES and components.city != parts[-1]:
            components.city, components.region = parts[-1], None
            components.neighborhood = parts[0]
            components.area = ", ".join(parts[1:-1]) or None
    if state is not None and components.region is None:
        components.region = state

    # Look for a landmark anchor in the text near the address span
    anchor_match = _find_anchor_near(full_text, span)
    if anchor_match is not None:
        components.anchor, components.anchor_type = anchor_match
        # Extend the span to include the anchor if it's adjacent
        start = min(span[0], _find_anchor_start(full_text, span))
        span = (start, span[1])
        raw = full_text[start:span[1]].strip()

    if components.anchor is None and tail_anchor is not None:
        components.anchor = tail_anchor
        components.anchor_type = _classify_anchor(tail_anchor)

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


# What closes an address: a GB postcode, a US state and ZIP, or a number after
# the town inside a comma part ("Westlands, Nairobi 00100"). A bare number in
# text with no commas is not read: it may be anything.
_US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|"
    "NJ|NM|NY|NC|ND|OH|OK|OR|PA|PR|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY")
_COUNTRY_END_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?:usa?|united states|uk|united kingdom|gb|england|scotland|wales)$")
_US_END_RE = re.compile(
    r"(?i)(?<![A-Za-z])(?P<state>" + _US_STATES + r")[\s,]{1,3}(?P<pc>\d{5}(?:-\d{4})?)$")
_CODE_END_RE = re.compile(r"(?<![\w/-])(?P<pc>\d{4,6})$")
_GB_END_RE = re.compile(r"(?<![A-Za-z0-9])(?P<pc>" + _GB_POSTCODE + r")$")

# Counties that close a UK address before the postcode; some are also towns
# elsewhere ("Cheshire" in Connecticut).
_UK_COUNTIES = frozenset([
    "bedfordshire", "berkshire", "buckinghamshire", "cambridgeshire", "cheshire", "cornwall",
    "cumbria", "derbyshire", "devon", "dorset", "county durham", "east sussex",
    "east yorkshire", "essex", "gloucestershire", "greater london", "greater manchester",
    "hampshire", "herefordshire", "hertfordshire", "isle of wight", "kent", "lancashire",
    "leicestershire", "lincolnshire", "merseyside", "middlesex", "norfolk",
    "north yorkshire", "northamptonshire", "northumberland", "nottinghamshire",
    "oxfordshire", "rutland", "shropshire", "somerset", "south yorkshire", "staffordshire",
    "suffolk", "surrey", "tyne and wear", "warwickshire", "west midlands", "west sussex",
    "west yorkshire", "wiltshire", "worcestershire", "yorkshire", "gwent", "dyfed", "powys",
    "clwyd", "gwynedd", "aberdeenshire", "angus", "argyll", "ayrshire", "fife",
    "lanarkshire", "renfrewshire", "perthshire",
])


# No address runs longer than this after its street. Text beyond it is prose,
# and everything below reads only this much, so a long line costs no more.
_MAX_REST = 240


def _closing_code(rest: str) -> tuple[str, str | None, str | None]:
    """``rest`` without the postcode that closes it, the postcode, and a US state.

    Only the last few words are matched: a pattern that also consumed what
    comes before them would cost the square of a long line.
    """
    if len(rest) > _MAX_REST:
        return rest, None, None
    t = rest.rstrip(" .,")
    cut = t
    for _ in range(2):
        at = max(0, len(cut) - 24)
        end = cut[at:]
        m = _GB_END_RE.search(end)
        if m is not None:
            return cut[:at + m.start()], normalise_gb_postcode(m.group("pc")), None
        m = _US_END_RE.search(end)
        if m is not None:
            return cut[:at + m.start()], m.group("pc"), m.group("state")
        m = _CODE_END_RE.search(end)
        if m is not None:
            head = cut[:at + m.start()].rstrip()
            town = head.rpartition(",")
            if town[1] and re.fullmatch(r"\s*[A-Za-z][^,\d]*[A-Za-z]", town[2]) \
                    and not _BOX_IN_PART_RE.search(cut):
                return head, m.group("pc"), None
        # Once more without a closing country: "... Bellport NY 11713, us".
        country = _COUNTRY_END_RE.search(cut[max(0, len(cut) - 24):])
        if country is None:
            break
        cut = cut[:max(0, len(cut) - 24) + country.start()].rstrip(" .,")
    return rest, None, None


def _town_suffix(words: str) -> list[str]:
    """``words`` that a postcode follows, as ``[area, town]`` or ``[town]``.

    The town is the longest ending the place list knows as a town. Where it
    knows none, the words are one place.
    """
    w = words.split()
    for k in range(min(4, len(w)), 0, -1):
        town = " ".join(w[-k:])
        if _places.town_rank(town) >= 3:
            head = " ".join(w[:-k])
            return [head, town] if head else [town]
    return [words]


_TAIL_SEGMENT_RE = re.compile(
    r"(?:(?:[A-Z][\w'\-]+\s+){0,2}(?:[A-Z]\.){1,4}[A-Z]?\.?"      # "Kanyiri G.R.A."
    r"(?:\s+[A-Z][\w'\-]+){0,2})|" + _TAIL_SEGMENT)
# A stop or junction is a landmark; an estate or quarter is an area.
_STOP_END_RE = re.compile(r"(?i)\b(?:bus[\s-]?stop|b/stop|junction|round\s*about)\.?$")
_AREA_END_RE = re.compile(
    r"(?i)^\S+(?:\s+\S+){0,3}\s+(?:estate|layout|quarters|village|extension|area)\.?$")
_BOX_IN_PART_RE = re.compile(r"(?i)\b(?:p\.?\s*o\.?\s*)?box\s*\d|\bp\.?\s*m\.?\s*b\.?\s*\d")


def _tail_after(
    text: str, start: int,
) -> tuple[str, str | None, str | None, str | None]:
    """The places after a street, the first landmark between them, and the
    postcode and US state that close the line.

    Reads the comma-separated parts from ``start`` to the end of the line. A
    part that begins with a landmark word ("OFF OBODO/KANYIRI ROAD", "By
    Ajala Bus Stop", "Near Obodo Cinema") or names a second road is a landmark;
    a P.O. box or PMB part, or a unit, is passed over. The places are the
    parts after those, each read as a tail segment; reading stops at the first
    part that is not one, so a sentence after an address ("..., Ikeja and then
    Lagos") gives "Ikeja", as the segment pattern alone did.
    """
    end = text.find("\n", start)
    stop = len(text) if end < 0 else end
    rest, code, state = _closing_code(text[start:min(stop, start + _MAX_REST + 1)])
    chunks = rest[:_MAX_REST].split(",")
    places: list[str] = []
    anchor: str | None = None
    # Straight after the street, before any comma: a town only if the place
    # list knows it ("22 Ajala Road Ibadan"), or a postcode closes the line;
    # anything else ends the tail.
    first = chunks[0].strip(" .")
    if first and (_LANDMARK_START_RE.match(first) or _LANDMARK_WORD_RE.match(first)):
        landmark, town = _town_at_end(first)
        anchor = _clean(landmark)
        if town:
            places.append(town)
    elif first:
        known = (_AREA_END_RE.search(first) or _places.town_rank(first) >= 3
                 or any(_places.focus_rank(p) for p in _split_places(first)))
        if known:
            places.append(first)
        elif code is not None and len(first.split()) <= 6 and not re.search(r"\d", first):
            places += _town_suffix(first) if len(chunks) == 1 else [first]
        else:
            return "", None, code, state
    road_part: str | None = None       # the last part, if it was set aside as a road
    for raw in chunks[1:]:
        part = raw.strip(" .")
        if not part:
            continue
        if code is not None:
            part = re.sub(r"\bSt\.\s", "St ", part)
        road_part = None
        # A second road is a short part; a long one is prose running on
        # ("Lagos and copy the invoice to 12 Long Street").
        second_road = (len(part.split()) <= 6
                       and re.search(r"(?i)\b" + _STREET_SUFFIX_RE, part))
        if (_LANDMARK_START_RE.match(part) or _LANDMARK_WORD_RE.match(part) or second_road
                or _STOP_END_RE.search(part)):
            # A landmark may end in the town: "Off Obodo Road Ibadan".
            landmark, town = _town_at_end(part)
            anchor = anchor or _clean(landmark)
            if town:
                places.append(town)
            elif second_road and not re.search(r"\d", part):
                road_part = part
            continue
        if _BOX_IN_PART_RE.search(part) or _UNIT_RE.fullmatch(part):
            continue
        # A postcode closes the line, so it is an address to its end: a part is a
        # place however it is written ("Burton on Trent").
        if code is not None and len(part.split()) <= 5 and not re.search(r"\d", part):
            places.append(part)
            continue
        seg = _TAIL_SEGMENT_RE.match(part)
        if seg is None:
            break
        places.append(seg.group(0))
        if seg.end() < len(part):
            break
    # "68 Ajala Road, Earls Court, SW5 0RD": a town named like a road.
    if code is not None and not places and road_part is not None:
        places.append(road_part)
        anchor = None if anchor == road_part else anchor
    return ", ".join(_order_places(places)), anchor, code, state


def _town_at_end(part: str) -> tuple[str, str | None]:
    """A landmark and the town after it, when the town has no comma before it.

    The town is the words after the landmark's last road or landmark word
    ("... Road Ibadan", "... Bus Stop Ibadan"), when the place list
    knows them as a town.
    """
    last = None
    for m in re.finditer(r"(?i)\b(?:" + "|".join(_STREET_SUFFIXES) + r"|" + _ANCHOR_NOUN_RE
                         + r"|b/stop|stop|stage|garage|estate)\b\.?", part):
        last = m
    if last is None:
        return part, None
    town = part[last.end():].strip(" .")
    if 1 <= len(town.split()) <= 3 and (_places.focus_rank(town) >= 2
                                       or _places.town_rank(town) >= 3):
        return part[:last.end()].strip(), town
    return part, None


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


def _build_landmark_address_from_match(m: re.Match[str], full_text: str) -> Address | None:
    """Build an Address from a landmark-anchored span with no street suffix.

    Precision gate: emit only when the landmark is a recognised place-type
    (filling station, mosque, junction, ...) OR the tail yields a known
    locality. Otherwise an incidental phrase like "behind the President" would
    be mistaken for an address.
    """
    anchor_text = m.group("anchor")
    anchor_type = _classify_anchor(anchor_text)

    components = AddressComponents(anchor=anchor_text, anchor_type=anchor_type)
    _parse_tail(m.groupdict().get("tail") or "", components)

    has_locality = bool(
        components.city or components.neighborhood or components.postal_code
    )
    if anchor_type == "other" and not has_locality:
        return None

    country, country_conf = _infer_country(components, full_text)
    components.country = country

    # Landmark-only addresses are inherently less precise than street/box ones.
    confidence = min(_score_address(components), 0.6)

    return Address(
        raw=m.group(0).strip(),
        span=(m.start(), m.end()),
        components=components,
        country_inferred=country,
        country_confidence=country_conf,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Internal: tail parsing (city, region, country, postal)
# ---------------------------------------------------------------------------

_REGION_PART_RE = re.compile(r"(?i)\s(state|region|county|province)\.?$")


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

    # A GB postcode, alone in its part or trailing a town ("London NW1 6XE").
    # Checked before the generic digit shapes, and normalised ("nw16xe" ->
    # "NW1 6XE"). A town in front of it stays a part of its own, so the city
    # reads "London" rather than "London NW1".
    for i, part in enumerate(parts):
        whole = normalise_gb_postcode(part)
        if whole is not None:
            components.postal_code = whole
            parts.pop(i)
            break
        m = _GB_POSTCODE_SUFFIX_RE.match(part)
        if m is not None:
            components.postal_code = normalise_gb_postcode(m.group("pc"))
            parts[i] = m.group("head").strip()
            break

    # Detect postal code in the tail
    for i, part in enumerate(parts):
        if components.postal_code is not None:
            break
        if _looks_like_postal_code(part):
            components.postal_code = part
            parts.pop(i)
            break

    if not parts:
        return

    # A last part that names its own level is the region: "Lagos State",
    # "Greater Accra Region", "Kiambu County", "Western Cape Province". Without
    # this, "Lagos State" hit the gazetteer as a city and pushed the real town
    # ("Ikorodu, Lagos State") down to neighborhood.
    if len(parts) >= 2 and _REGION_PART_RE.search(parts[-1]):
        components.region = parts[-1]
        parts = parts[:-1]

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


def _find_unit_near(text: str, address_span: tuple[int, int]) -> str | None:
    """A unit in the address or just around it, on the same line.

    "5th Floor, 18 Moi Avenue" puts the floor before the street the parser
    matches. The window stops at a line break, so a unit from a neighbouring
    line of a document is not attached.
    """
    start, end = address_span
    before = text[max(0, start - 60):start].rsplit("\n", 1)[-1]
    after = text[end:end + 40].split("\n", 1)[0]
    m = _UNIT_RE.search(before + text[start:end] + after)
    return _clean(m.group(0)) if m else None


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
        if normalise_gb_postcode(components.postal_code) is not None:
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
    "normalise_gb_postcode",
    "parse_address",
    "parse_addresses",
]
