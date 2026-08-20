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

"""Lightweight Fellegi-Sunter probabilistic identity matcher.

Replaces Splink as the primary matching engine for small record sets (< 100
records).  Splink remains available as an optional backend for large-scale
batch deduplication.

Usage::

    from arche import match

    score = match("Mamadou Diallo", "Mohamed Diallo")  # → MatchScore(0.89)
    score = match("Acme SARL", "Acme Ltd")             # → MatchScore(0.93)

The matcher uses pre-computed m/u probabilities (Fellegi-Sunter weights) with
cultural name equivalence, phonetic similarity, and normalised exact matching
for identifiers.  Jurisdiction-specific priors adjust u-probabilities based on
name frequency (e.g. "Mohammed" is far more common in Nigeria than in France).
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

_log = logging.getLogger("arche")


# ===================================================================
# Data types
# ===================================================================


@dataclass
class MatchScore:
    """Result of comparing two entities or identity records."""

    score: float  # 0.0–1.0 probability that the two refer to the same entity
    decision: str  # "match", "review", "no_match"
    factors: dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def __repr__(self) -> str:
        return (
            f"MatchScore(score={self.score:.4f}, decision={self.decision!r})"
        )

    def __float__(self) -> float:
        return self.score


@dataclass
class JurisdictionPriors:
    """Pre-computed m/u probabilities for a jurisdiction.

    m = P(field agrees | true match)
    u = P(field agrees | true non-match)
    """

    name: str = "default"

    # Name field
    name_m: float = 0.92  # P(names agree | same person)
    name_u: float = 0.01  # P(names agree | different person)

    # Phone field
    phone_m: float = 0.95
    phone_u: float = 0.00001

    # National ID field
    national_id_m: float = 0.999
    national_id_u: float = 0.000001

    # Address field
    address_m: float = 0.85
    address_u: float = 0.05

    # Date of birth field
    dob_m: float = 0.95
    dob_u: float = 0.003  # ~1/365

    # Email field
    email_m: float = 0.98
    email_u: float = 0.000001

    # Geo (lat/lon proximity) field
    geo_m: float = 0.90   # P(points are close | same real-world place)
    geo_u: float = 0.15   # P(points are close | different places in the same block)

    # Thresholds
    match_threshold: float = 0.85
    review_threshold: float = 0.40

    # Common name adjustments: name → u-probability override
    # (populated per jurisdiction from name frequency data)
    common_name_u: dict[str, float] = field(default_factory=dict)


# ===================================================================
# Built-in jurisdiction priors
# ===================================================================

# These are initial estimates.  As the data flywheel produces labelled
# match pairs, these will be refined from empirical data.

_JURISDICTION_PRIORS: dict[str, JurisdictionPriors] = {
    "default": JurisdictionPriors(name="default"),

    "NG": JurisdictionPriors(
        name="Nigeria",
        name_u=0.02,  # higher because common names (Mohammed, Abubakar) are frequent
        phone_u=0.00001,
        national_id_u=0.000001,
        address_u=0.06,  # informal addresses reduce specificity
        common_name_u={
            "mohammed": 0.08, "muhammad": 0.08, "mohamed": 0.08,
            "abubakar": 0.05, "ibrahim": 0.05, "abdullahi": 0.04,
            "musa": 0.04, "usman": 0.03, "adamu": 0.03,
            "fatima": 0.04, "amina": 0.04, "aisha": 0.03,
        },
    ),

    "GH": JurisdictionPriors(
        name="Ghana",
        name_u=0.02,
        common_name_u={
            "kwame": 0.06, "ama": 0.06, "kofi": 0.05, "akua": 0.05,
            "yaa": 0.04, "kwesi": 0.04, "efua": 0.03,
            "mohammed": 0.05, "ibrahim": 0.04,
        },
    ),

    "KE": JurisdictionPriors(
        name="Kenya",
        name_u=0.015,
        common_name_u={
            "john": 0.04, "james": 0.03, "peter": 0.03, "mary": 0.04,
            "mohamed": 0.03, "hassan": 0.02, "wanjiku": 0.03,
        },
    ),

    "ZA": JurisdictionPriors(
        name="South Africa",
        name_u=0.012,
        common_name_u={
            "john": 0.03, "sipho": 0.03, "thabo": 0.025,
            "nomsa": 0.02, "lindiwe": 0.02, "mohammed": 0.02,
        },
    ),

    "FR": JurisdictionPriors(
        name="France",
        name_u=0.008,
        common_name_u={
            "jean": 0.04, "pierre": 0.03, "marie": 0.05,
            "mohammed": 0.03, "nicolas": 0.02,
        },
    ),
}


def get_priors(jurisdiction: str = "default") -> JurisdictionPriors:
    """Get m/u priors for a jurisdiction.  Falls back to default."""
    return _JURISDICTION_PRIORS.get(jurisdiction.upper(), _JURISDICTION_PRIORS["default"])


# ===================================================================
# Comparison functions
# ===================================================================


def _normalise_text(text: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace."""
    text = text.strip().lower()
    nfkd = unicodedata.normalize("NFKD", text)
    # Drop combining marks AND format/control codepoints (zero-width spaces,
    # RTL overrides, control chars) so they can't split one name into two
    # (match evasion) or spoof rendered output.
    stripped = "".join(
        c for c in nfkd
        if not unicodedata.combining(c) and unicodedata.category(c) not in ("Cf", "Cc")
    )
    return re.sub(r"\s+", " ", stripped)


def _normalise_id(text: str) -> str:
    """Strip all non-alphanumeric characters and lowercase."""
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()


def _jaro_winkler(a: str, b: str) -> float:
    """Jaro-Winkler similarity with fallback."""
    try:
        from jellyfish import jaro_winkler_similarity
        return jaro_winkler_similarity(a, b)
    except ImportError:
        pass
    try:
        from rapidfuzz.distance import JaroWinkler
        return JaroWinkler.similarity(a, b)
    except ImportError:
        return 1.0 if a == b else 0.0


def _token_sort_ratio(a: str, b: str) -> float:
    """Token-sorted fuzzy ratio (0-1)."""
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100.0
    except ImportError:
        return 1.0 if a == b else 0.0


def _names_are_equivalent(a: str, b: str) -> tuple[bool, float]:
    """Check cultural name equivalence via arche's African names module."""
    try:
        from ..detect._names.lexicon import are_names_equivalent
        return are_names_equivalent(a, b)
    except (ImportError, Exception):
        return (False, 0.0)


def compare_names(
    name_a: str,
    name_b: str,
    priors: JurisdictionPriors | None = None,
) -> tuple[float, float]:
    """Compare two names.

    Returns (similarity, u_probability).
    similarity: 0.0–1.0 how similar the names are.
    u_probability: jurisdiction-adjusted u for these specific names.
    """
    priors = priors or get_priors()

    norm_a = _normalise_text(name_a)
    norm_b = _normalise_text(name_b)

    if not norm_a or not norm_b:
        return (0.0, priors.name_u)

    # Exact match after normalisation
    if norm_a == norm_b:
        # Look up common name u-probability
        u = priors.common_name_u.get(norm_a, priors.name_u)
        return (1.0, u)

    # Cultural name equivalence (highest priority)
    equiv, equiv_confidence = _names_are_equivalent(name_a, name_b)
    if equiv:
        # Check if any token is a common name
        tokens = set(norm_a.split()) | set(norm_b.split())
        max_u = priors.name_u
        for token in tokens:
            max_u = max(max_u, priors.common_name_u.get(token, 0.0))
        return (equiv_confidence, max_u)

    # String similarity (Jaro-Winkler on full name, token-sort for reordering)
    jw = _jaro_winkler(norm_a, norm_b)
    ts = _token_sort_ratio(norm_a, norm_b)
    best = max(jw, ts)

    # Check if any token is a common name
    tokens = set(norm_a.split()) | set(norm_b.split())
    max_u = priors.name_u
    for token in tokens:
        max_u = max(max_u, priors.common_name_u.get(token, 0.0))

    return (best, max_u)


def compare_phones(phone_a: str, phone_b: str) -> float:
    """Compare two phone numbers.  Returns 1.0 if same after normalisation."""
    norm_a = _normalise_id(phone_a)
    norm_b = _normalise_id(phone_b)
    if not norm_a or not norm_b:
        return 0.0

    # Handle country code variations: +234xxx vs 0xxx
    # Strip leading country codes for comparison
    for prefix in ("234", "233", "254", "27", "225", "221"):
        if norm_a.startswith(prefix) and norm_b.startswith("0"):
            if norm_a[len(prefix):] == norm_b[1:]:
                return 1.0
        if norm_b.startswith(prefix) and norm_a.startswith("0"):
            if norm_b[len(prefix):] == norm_a[1:]:
                return 1.0

    return 1.0 if norm_a == norm_b else 0.0


def compare_ids(id_a: str, id_b: str) -> float:
    """Compare two national IDs.  Returns 1.0 if same after normalisation."""
    norm_a = _normalise_id(id_a)
    norm_b = _normalise_id(id_b)
    if not norm_a or not norm_b:
        return 0.0
    return 1.0 if norm_a == norm_b else 0.0


def compare_emails(email_a: str, email_b: str) -> float:
    """Compare two email addresses (case-insensitive)."""
    a = email_a.strip().lower()
    b = email_b.strip().lower()
    if not a or not b:
        return 0.0
    return 1.0 if a == b else 0.0


# Per-component distinctiveness weights for address comparison.
#
# African informal addresses are landmark-based ("behind the Total filling
# station, Madina") and have no canonical registry, so the operative locators
# are the landmark ``anchor`` and the ``street`` — weighted highest. A shared
# ``city``/``region`` is weak evidence (many people share a city), weighted low.
#
#     addr A                      addr B                     shared    signal
#     ----------------------      ----------------------     ------    ------
#     12 Long St, Cape Town       99 Main Rd, Cape Town      city      weak  → low score
#     behind Total FS, Madina     opposite Total FS, Madina  anchor    strong→ high score
#     7B Allen Ave                9B Allen Ave               number    differs→ pulled down
_ADDR_FIELD_WEIGHTS: dict[str, float] = {
    "anchor": 3.0,
    "street": 2.5,
    "postal_code": 2.0,
    "plot": 1.5,
    "street_number": 1.5,
    "neighborhood": 1.0,
    "city": 0.6,
    "region": 0.4,
}
# Fields specific enough that a strong match must share at least one of them.
_ADDR_DISTINCTIVE = {"anchor", "street", "postal_code", "plot", "street_number", "neighborhood"}
# Fields where a difference is a genuine difference, not a typo (exact-compared).
_ADDR_EXACT_FIELDS = {"plot", "street_number", "postal_code"}
# Cap applied when only low-distinctiveness fields (city/region) are shared.
_ADDR_WEAK_MATCH_CAP = 0.6

# Leading landmark prepositions/articles to strip so "behind the Total filling
# station" and "opposite Total Filling Station" compare on the landmark itself.
_ANCHOR_PREP_RE = re.compile(
    r"^(?:behind|near|opposite|beside|next to|in front of|across from|after|before)\s+(?:the\s+)?",
    re.IGNORECASE,
)


def _normalise_anchor(anchor: str) -> str:
    """Normalise a landmark anchor: drop the leading (possibly code-mixed)
    relation word + article via the shared addr vocabulary, then normalise.
    Falls back to the built-in English prepositions if addr is unavailable."""
    try:
        from ..addr import normalize_landmark

        anchor = normalize_landmark(anchor)
    except ImportError:
        anchor = _ANCHOR_PREP_RE.sub("", anchor)
    return _normalise_text(anchor)


# Matchable address component names (also the weight keys above).
_ADDR_COMPONENT_KEYS = set(_ADDR_FIELD_WEIGHTS)


def _coerce_address(addr: Any) -> tuple[str, dict[str, str]]:
    """Normalise an address input to ``(raw_string, matchable-components)``.

    Accepts a raw ``str`` (parsed on the fly), or a structured address the
    pipeline already parsed: a mapping (e.g. an address Detection's metadata,
    ``{"text": ..., "street": ..., "anchor": ...}``) or an
    :class:`~arche.addr.AddressComponents`. Structured input skips re-parsing
    and uses the pipeline's landmark ``anchor`` directly.
    """
    if isinstance(addr, str):
        return addr, _address_components(addr)
    if isinstance(addr, Mapping):
        source: dict[str, Any] = dict(addr)
    elif hasattr(addr, "__dict__"):  # AddressComponents / dataclass instance
        source = dict(vars(addr))
    else:
        text = str(addr)
        return text, _address_components(text)

    comps = {
        key: str(value)
        for key, value in source.items()
        if key in _ADDR_COMPONENT_KEYS and value
    }
    raw = str(source.get("text") or source.get("raw") or "")
    if not raw:
        raw = ", ".join(comps.values())
    return raw, comps


def _address_components(addr: str) -> dict[str, str]:
    """Parse an address string into a dict of non-empty matchable components.

    Falls back to a standalone landmark-anchor extraction when the full parser
    recovers no structured address (the common African landmark-only case).
    ``country`` and ``anchor_type`` are dropped — they are not per-record
    matching signals. Returns ``{}`` when nothing structured is found.
    """
    try:
        from ..addr import extract_anchor, parse_address
    except ImportError:
        return {}

    fields: dict[str, str] = {}
    parsed = parse_address(addr)
    if parsed is not None:
        for key, value in vars(parsed.components).items():
            if value:
                fields[key] = value
    if "anchor" not in fields:
        anchor = extract_anchor(addr)
        if anchor is not None:
            fields["anchor"] = anchor[0]
    fields.pop("anchor_type", None)
    fields.pop("country", None)
    return fields


def _component_field_sim(field_name: str, a: str, b: str) -> float:
    """Similarity for a single address component."""
    if field_name == "anchor":
        na, nb = _normalise_anchor(a), _normalise_anchor(b)
    else:
        na, nb = _normalise_text(a), _normalise_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if field_name in _ADDR_EXACT_FIELDS:
        # A different house/plot number or postcode is a real difference.
        return 0.0
    return max(_jaro_winkler(na, nb), _token_sort_ratio(na, nb))


def compare_addresses(addr_a: Any, addr_b: Any) -> float:
    """Compare two addresses using their parsed structure.

    Raw-string similarity both over-matches (two unrelated addresses that
    share "Lagos") and under-matches (the same landmark described two ways),
    and it discards everything ``arche.addr`` worked to parse. This compares
    component-by-component, weighting the landmark ``anchor`` and ``street``
    as high-distinctiveness signals and a shared ``city``/``region`` as weak.
    Falls back to raw-string similarity only when neither side yields
    structure (so token-reordering like "Ikeja Lagos" vs "Lagos Ikeja" is
    still handled).

    Accepts a raw string or a structured address (mapping / AddressComponents)
    the pipeline already parsed, so the landmark anchor isn't lost to a
    round-trip through a flattened string.

    Future: spatial proximity via geocoding / gazetteer centroids.
    """
    raw_a, comps_a = _coerce_address(addr_a)
    raw_b, comps_b = _coerce_address(addr_b)
    norm_a = _normalise_text(raw_a)
    norm_b = _normalise_text(raw_b)
    if not (norm_a or comps_a) or not (norm_b or comps_b):
        return 0.0
    if norm_a and norm_a == norm_b:
        return 1.0

    shared = set(comps_a) & set(comps_b)

    # Nothing structured in common: fall back to raw fuzzy similarity.
    if not shared:
        return max(_token_sort_ratio(norm_a, norm_b), _jaro_winkler(norm_a, norm_b))

    weighted_sum = 0.0
    weight_total = 0.0
    for field_name in shared:
        weight = _ADDR_FIELD_WEIGHTS.get(field_name, 0.5)
        weighted_sum += weight * _component_field_sim(
            field_name, comps_a[field_name], comps_b[field_name]
        )
        weight_total += weight
    score = weighted_sum / weight_total if weight_total else 0.0

    # A match resting only on shared city/region is weak — cap it.
    if not (shared & _ADDR_DISTINCTIVE):
        score = min(score, _ADDR_WEAK_MATCH_CAP)

    return score


def haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance in kilometres between two points."""
    radius_km = 6371.0088  # mean Earth radius
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    dphi = math.radians(lat_b - lat_a)
    dlambda = math.radians(lon_b - lon_a)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(min(1.0, math.sqrt(h)))


def compare_geo(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    *,
    decay_km: float = 1.5,
) -> float:
    """Similarity in [0, 1] from the great-circle distance between two points.

    Haversine distance with an exponential decay: 1.0 at the same point,
    ~0.37 at ``decay_km``, ~0.05 at ~3x ``decay_km``. ``decay_km`` is
    deliberately forgiving because field-captured coordinates are noisy — in
    African facility data roughly a quarter of true-match pairs sit >2 km
    apart — so geo is a supporting signal, never a hard gate. Generic
    geospatial comparator; not tied to any entity type.
    """
    distance_km = haversine_km(lat_a, lon_a, lat_b, lon_b)
    if decay_km <= 0:
        return 1.0 if distance_km == 0 else 0.0
    return math.exp(-distance_km / decay_km)


def compare_place_names(name_a: str, name_b: str) -> float:
    """Fuzzy similarity for PLACE names — deliberately lexicon-free.

    Place names must never route through the person cultural-name equivalence
    lexicon: "Fatima Hospital" and "Fatouma Hospital" are plausibly two
    *different* facilities named after two different people, but the person
    lexicon scores Fatima≡Fatouma at 1.0 — a false-merge vector. This
    comparator is plain normalised string similarity (exact -> 1.0, else the
    max of Jaro-Winkler and token-sort ratio), so agreement is earned by the
    strings themselves and rarity weighting is left to the ``tftoken``
    comparator alongside it.
    """
    na, nb = _normalise_text(name_a), _normalise_text(name_b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return max(_jaro_winkler(na, nb), _token_sort_ratio(na, nb))


# A trailing parenthetical, or everything after the first comma. Anchored and
# non-greedy so `Moorfields Eye Hospital (City Road campus)` splits at the last
# parenthesis rather than the first.
_QUALIFIER_PAREN = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def split_place_name(name: str) -> tuple[str, str]:
    """Split a place name into ``(core, qualifier)``.

    Sources disambiguate places by appending the containing region, and they do
    not agree on how. Measured on the Leipzig Geographic Settlements benchmark,
    the same four sources describe one settlement four ways::

        NYTimes   Petra (Jordan)        99.7% qualified
        DBpedia   Cordoba, Spain        36.8% qualified
        Freebase  savannah               0.0% qualified
        GeoNames  Split                  0.0% qualified

    A name comparator treats the qualifier as part of the identifying string,
    so ``Marseille (France)`` against ``Marseille`` scored 0.661 — below the
    match threshold — while the distinctiveness gate was clearing comfortably
    at 0.90. The failure was representation, not thresholds.

    Splitting lets the name comparator compare names and the qualifier be
    weighed separately, which is what it is: a containment hint, not part of
    the identity.

    ``('Petra', 'Jordan')``, ``('Cordoba', 'Spain')``, ``('Split', '')``.

    A qualifier is only reported when a non-empty core remains, so ``(Jordan)``
    stays whole rather than becoming an anonymous qualifier. Only the first
    comma splits, so ``Moorfields Eye Hospital (City Road campus)`` keeps its
    campus as the qualifier and multi-comma names keep the remainder together.
    """
    text = (name or "").strip()
    if not text:
        return "", ""
    m = _QUALIFIER_PAREN.match(text)
    if m:
        core, qualifier = m.group(1).strip(), m.group(2).strip()
        if core and qualifier:
            return core, qualifier
        return text, ""
    if "," in text:
        core, _, qualifier = text.partition(",")
        core, qualifier = core.strip(), qualifier.strip()
        if core and qualifier:
            return core, qualifier
    return text, ""


def compare_place_qualifiers(name_a: str, name_b: str) -> float | None:
    """Similarity of two place names' *qualifiers*, or ``None`` if either lacks one.

    ``None`` rather than 0.0 is the whole point: most sources qualify some names
    and not others, and an unqualified name is missing evidence, not a
    disagreement. Scoring absence as 0.0 would punish exactly the cross-source
    pairs this comparator exists to help.

    Deliberately lexicon-free and fuzzy, like :func:`compare_place_names`,
    because qualifiers are written at different granularities and in different
    forms — ``NY`` against ``New York``, ``Calif`` against ``California``.
    Those abbreviations are why this is a *scored* signal rather than a
    refutation: as a ``refutes_below`` discriminator it removed 13 false merges
    but cost 17 true ones, a trade a fuzzy field cannot reliably make.
    """
    qa = split_place_name(name_a)[1]
    qb = split_place_name(name_b)[1]
    if not qa or not qb:
        return None
    return compare_place_names(qa, qb)


# ── categorical geography: admin units and postal codes ────────────────────
#
# Both are labels attached to a point by asking which polygon contains it, and
# both therefore disagree at boundaries for reasons that have nothing to do
# with identity. They share one treatment and one vocabulary below.
#
# `_CATEGORICAL_NEUTRAL` is the value that means "no comparable evidence".
# is the value `compare_containment` already returned when no level was
# comparable on both sides. It sits BELOW the weakest agreement either
# comparator can award (0.3 for a shared admin1, 0.5 for a shared postcode
# district), so a discounted disagreement can never be read as agreement,
# however near the boundary the pair sits.
_CATEGORICAL_NEUTRAL = 0.2

# How far apart two points can be and still plausibly straddle ONE admin
# boundary. Derived, not fitted:
#
#   * The label comes from a point-in-polygon join, so two joins disagree
#     whenever the point sits within the boundary layer's own positional error
#     of the line. National admin layers in common use (GADM, OSM-derived
#     relations, humanitarian COD-AB) are digitised at scales whose stated
#     positional accuracy runs from ~100 m to ~1 km, so 1 km is the generous
#     end of "could be the same side of the line".
#   * It is 10x tighter than the `place` pack's `veto_km` of 10 km, so
#     refutation is only ever withheld inside a band where the geo comparator
#     is itself still scoring the pair as close.
#
# Sanity check, NOT the derivation: on the two state-border false merges in the
# Nigeria school register the band separates them (0.72 km inside, 8.77 km
# outside). Two observations cannot calibrate a threshold and this one was not
# calibrated on them.
BOUNDARY_UNCERTAINTY_KM = 1.0

# The postal-code equivalent, and much tighter because a postal unit is much
# smaller than a state. A UK unit postcode covers ~15 delivery points, often one
# side of one street, so two different unit codes 100 m apart routinely straddle
# one boundary. This default is sized for the FINEST common granularity on
# purpose: too tight merely restores full refutation (the safe direction), while
# too wide withholds refutation from pairs that genuinely disagree. Coarser
# formats need it raised explicitly: roughly 2 km for a GB outward code, a US
# 5-digit ZIP, or an NG 6-digit code.
POSTCODE_BOUNDARY_UNCERTAINTY_KM = 0.1

# A shared postcode district with differing units: the same evidence shape as a
# shared admin2 with differing settlements, and scored between the two.
_POSTCODE_DISTRICT_AGREEMENT = 0.5


def boundary_doubt(distance_km: float | None, boundary_km: float) -> float:
    """How far to discount a categorical geographic disagreement, in [0, 1].

    Returns 1.0 when the two points are close enough that the disagreement
    carries no information (a boundary artefact), falling linearly to 0.0 at
    ``boundary_km``, where the disagreement is taken at face value. Callers
    multiply :data:`_CATEGORICAL_NEUTRAL` by this, so 1.0 means "score this as
    no evidence" and 0.0 means "score this as a refutation".

    **Why linear with a hard floor**, rather than the exponential decay
    :func:`compare_geo` uses. An exponential never reaches zero, so a
    disagreement would never be refuted in full at any distance, and there
    would be no distance at which the pre-existing behaviour resumes exactly.
    The floor gives a checkable point: at and beyond ``boundary_km`` this
    returns exactly 0.0 and the comparator returns exactly 0.0, which is what
    it returned before this discount existed.

    Edge cases, all of which fall back to full refutation (0.0) because absent
    or unusable evidence must never soften a disagreement:

    * ``distance_km is None``: no coordinates on one or both sides.
    * ``boundary_km <= 0``: the discount is switched off.
    * a non-finite or negative distance.
    """
    if distance_km is None or boundary_km <= 0:
        return 0.0
    if not math.isfinite(distance_km) or distance_km < 0:
        return 0.0
    return max(0.0, 1.0 - distance_km / boundary_km)


def compare_containment(
    path_a: Mapping[str, Any] | None,
    path_b: Mapping[str, Any] | None,
    *,
    levels: tuple[str, ...] = ("admin1", "admin2", "settlement"),
    distance_km: float | None = None,
    boundary_km: float = BOUNDARY_UNCERTAINTY_KM,
) -> float | None:
    """Admin-containment agreement between two points' admin paths.

    Each ``path`` maps an admin level (coarse -> fine: ``admin1`` state,
    ``admin2`` LGA, ``settlement``) to its name — the output of a point-in-polygon
    spatial join (``annotate_admin``, an ``arche-core[geo]`` extra). Returns a
    similarity in [0, 1], or ``None`` when neither side carries any admin level.

    Used as a coarse GATE, not a fine matcher: a disagreement at the coarsest
    level (different ``admin1``/state) returns 0.0, strong evidence two
    points are different places. Downstream, ``reconcile`` demotes any
    would-be match carrying a containment conflict to review rather than
    auto-vetoing it.

    The walk is TOP-DOWN (coarse -> fine) and stops at the first disagreement,
    awarding only the deepest agreement reached *before* it. This matters
    because settlement names repeat heavily within states (Sabon Gari, Tudun
    Wada, Unguwar Rimi): two points in the same state but *different* LGAs
    whose settlements merely share a name must not score as co-located — the
    LGA disagreement caps them at the state-level score.

    Boundary awareness
    ------------------
    **Administrative disagreement is not distance.** Two records in different
    states 720 m apart are almost certainly one place whose position falls
    within the boundary layer's error: a GPS fix at the gate rather than the
    road, a school serving both sides of a line. Two records in different
    states 500 km apart are certainly different places. Scoring both at 0.0
    treats a boundary artefact as proof of difference.

    So when ``distance_km`` is supplied, a coarsest-level disagreement is
    refuted *in proportion to distance*: it returns
    ``_CATEGORICAL_NEUTRAL * boundary_doubt(distance_km, boundary_km)``, which
    is :data:`_CATEGORICAL_NEUTRAL` (the function's own "no comparable
    evidence" value) at zero distance and falls linearly to exactly 0.0 at
    ``boundary_km``. ``reconcile`` raises its conflict flag on exactly 0.0, so
    refutation is *withheld* inside the band and is unchanged outside it.

    This can only ever withhold a refutation; it cannot manufacture one, and it
    cannot manufacture agreement. The discounted value is capped at 0.2, below
    the 0.3 awarded for a genuinely shared ``admin1``, so a disagreement never
    scores as well as the weakest agreement no matter how close the pair is.
    The distinctive-signal gate is untouched and still governs.

    Edge cases:

    * **No coordinates** (``distance_km is None``): the pre-existing 0.0 and
      its conflict, unchanged. Absent evidence cannot soften a disagreement,
      the same rule that stops absent coordinates firing ``veto_km``.
    * ``boundary_km <= 0`` switches the discount off entirely.
    * **Mid-hierarchy disagreement is deliberately left alone.** A differing
      LGA inside an agreeing state already returns the state-level score rather
      than 0.0, so it never refutes and has nothing to withhold; discounting it
      further could only *raise* it toward the deeper agreement it did not
      earn, which would manufacture evidence.
    """
    if not path_a or not path_b:
        return None
    finest_score = {"settlement": 1.0, "admin2": 0.6, "admin1": 0.3}
    best: float | None = None
    for level in levels:  # coarse -> fine
        na, nb = path_a.get(level), path_b.get(level)
        if not na or not nb:
            continue  # missing on a side: no evidence at this level, keep walking
        if _normalise_text(str(na)) != _normalise_text(str(nb)):
            if level == levels[0]:
                # Different coarsest unit -> disagreement, discounted by how
                # plausibly the pair merely straddles the boundary. Exactly 0.0
                # (the pre-existing hard disagreement) once past the band.
                return _CATEGORICAL_NEUTRAL * boundary_doubt(distance_km, boundary_km)
            # Mid-hierarchy disagreement: stop; award only what agreed above.
            return best if best is not None else _CATEGORICAL_NEUTRAL
        best = finest_score.get(level, 0.3)
    if best is not None:
        return best
    # No level comparable on both sides but no conflict -> weak.
    return _CATEGORICAL_NEUTRAL


# A GB postcode splits into a real two-level hierarchy: an outward code naming
# a postal district and an inward code naming a unit of ~15 delivery points.
# ZIP+4 splits the same way. Both splits are defined by the format itself. No
# prefix is guessed, because for a flat numeric code (NG 6-digit, US ZIP5) a
# shared prefix carries no containment meaning.
_GB_POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)(\d[A-Z]{2})$")
_ZIP_PLUS_4 = re.compile(r"^(\d{5})-(\d{4})$")


def _postcode_parts(text: str) -> tuple[str, str]:
    """Split a postal code into ``(district, unit)``; ``unit`` is "" if undefined."""
    raw = re.sub(r"\s+", "", (text or "").upper())
    m = _ZIP_PLUS_4.match(raw)
    if m:
        return m.group(1), m.group(2)
    flat = raw.replace("-", "")
    m = _GB_POSTCODE.match(flat)
    if m:
        return m.group(1), m.group(2)
    return flat, ""


def compare_postcodes(
    code_a: str,
    code_b: str,
    *,
    distance_km: float | None = None,
    boundary_km: float = POSTCODE_BOUNDARY_UNCERTAINTY_KM,
) -> float | None:
    """Postal-code agreement between two records, discounted at boundaries.

    Postal codes have the same property as admin units and the same failure
    mode: two records with different postcodes 50 m apart sit on a postcode
    boundary, while two records with different postcodes 30 km apart are
    different places. UK postcodes, US ZIPs and NG postal codes all behave this
    way. So a disagreement is refuted *in proportion to distance* by the shared
    :func:`boundary_doubt` ramp, identically to
    :func:`compare_containment`. See that docstring for the reasoning and for
    why the ramp is linear.

    Returns, in ``[0, 1]``, or ``None`` when either side is empty:

    ``1.0``
        Same code. Normalisation is whitespace-, case- and hyphen-insensitive,
        so ``SW1A 1AA``, ``sw1a1aa`` and ``SW1A-1AA`` are one code.
    ``0.5``
        Same district, different unit (``SW1A 1AA`` vs ``SW1A 2BB``;
        ``10001-1234`` vs ``10001-5678``). Real proximity evidence, and the
        reason this comparator parses a hierarchy at all: without it, two
        records on one street with adjacent unit codes would refute.
    ``0.2`` down to ``0.0``
        Different districts, ramped by distance. 0.2 at zero distance means
        "no evidence"; exactly 0.0 at and beyond ``boundary_km``.

    Unlike ``containment``, this kind does **not** hardwire a conflict flag.
    Declare ``refutes_below`` on the comparator spec to make it refute, using
    same generic mechanism every other refuting field uses. A ``None`` return
    can never fire it, so a missing postcode refutes nothing.

    Edge cases:

    * **Formats are not reconciled across countries.** A GB code is never
      compared against a ZIP as though they shared a hierarchy; they simply
      differ, and the distance ramp then decides. Feeding one field two
      countries' codes is a data-modelling error this cannot repair.
    * **Partial codes are compared as written.** ``SW1A`` against ``SW1A 1AA``
      scores 0.5 (district agreement), which is right. ``SW1`` against
      ``SW1A 1AA`` scores as a disagreement, because ``SW1`` and ``SW1A`` are
      different outward codes and truncating one to match the other would be
      guessing.
    * ``boundary_km <= 0``, absent coordinates, or a non-finite distance all
      give the undiscounted 0.0.
    """
    district_a, unit_a = _postcode_parts(code_a)
    district_b, unit_b = _postcode_parts(code_b)
    if not district_a or not district_b:
        return None
    if district_a == district_b:
        return 1.0 if unit_a == unit_b else _POSTCODE_DISTRICT_AGREEMENT
    return _CATEGORICAL_NEUTRAL * boundary_doubt(distance_km, boundary_km)


def normalize_type_token(text: str, vocab: dict[str, str]) -> tuple[str | None, str]:
    """Split a name into ``(canonical_type, residual_name)`` via a synonym vocab.

    ``vocab`` maps a synonym phrase to a canonical token, e.g.::

        {"phc": "PHC", "primary health centre": "PHC",
         "primary health care centre": "PHC", "dispensary": "DISPENSARY"}

    The longest synonym present in ``text`` (word-boundary match) is removed;
    the remainder is the residual proper name, so a matcher can compare the
    *distinctive* part ("Karfi", not the shared "Primary Health Centre") and
    the type separately. The same shape canonicalises organisation suffixes
    ("Ltd" / "PLC" / "SARL"), so it is generic, not facility-specific.

    Matching and the returned residual are normalised (lowercased, diacritics
    stripped). Returns ``(None, normalised_text)`` when no synonym matches.
    """
    low = _normalise_text(text)
    for syn in sorted(vocab, key=len, reverse=True):
        syn_norm = _normalise_text(syn)
        if not syn_norm:
            continue
        if re.search(r"\b" + re.escape(syn_norm) + r"\b", low):
            residual = re.sub(r"\b" + re.escape(syn_norm) + r"\b", " ", low)
            return vocab[syn], re.sub(r"\s+", " ", residual).strip()
    return None, low


@cache
def load_type_vocab(domain: str) -> dict[str, str]:
    """Load a type-token vocabulary for ``domain`` from ``type_tokens.yaml``.

    Returns a flat ``{synonym: canonical}`` map ready for
    :func:`normalize_type_token`. Domains (e.g. ``"health_facility"``,
    ``"organization"``) are the pack's top-level keys; each canonical token
    lists ``synonyms`` and a ``description``. Cached. Best-effort: an unknown
    domain, or a missing/invalid pack, returns ``{}`` (so callers can always
    fall back to fuzzy name matching). Treat the result as read-only.
    """
    path = Path(__file__).resolve().parent / "type_tokens.yaml"
    try:
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        return {}
    vocab: dict[str, str] = {}
    for canonical, spec in (data.get(domain) or {}).items():
        for syn in (spec or {}).get("synonyms") or []:
            vocab[str(syn)] = str(canonical)
        vocab.setdefault(str(canonical).lower(), str(canonical))
    return vocab


def compare_categories(cat_a: str, cat_b: str) -> float:
    """Compare two categorical labels — normalised exact match, 1.0 or 0.0.

    For closed vocabularies where a value means one thing: an entity class
    (``SITE`` / ``OPERATOR``), a tier, a status. Case, surrounding whitespace
    and internal separators are normalised, so ``washing_station``,
    ``Washing Station`` and ``WASHING-STATION`` are one value.

    Deliberately **not** in ``_DISTINCTIVE_KINDS``, and that is the whole point
    of it existing rather than reusing ``id``. Two records agreeing that both
    are a ``SITE`` is not evidence they are the *same* site — a low-entropy
    field shared by thousands of records must never clear the distinctive gate.
    An identifier is distinctive by construction; a class is the opposite.

    Its intended use is therefore as a pure discriminator, weighted at zero and
    refuting on disagreement::

        {"field": "entity_class", "kind": "category",
         "weight": 0.0, "refutes_below": 1.0}

    That is the only mechanism that separates a site from its operator, which
    is the largest false-merge risk in supply-chain data: ``Nyeri Hill
    Factory`` and ``Nyeri Hill Tea Factory Co Ltd`` share a name *and* a
    coordinate, so every string and spatial signal points the wrong way, and
    stripping the type token makes them *more* similar rather than less. Only a
    declared class refutes it, and only when both sides declare one — an absent
    class refutes nothing, exactly as absent coordinates cannot fire
    ``veto_km``.
    """
    norm_a = re.sub(r"[\s_\-]+", " ", cat_a).strip().casefold()
    norm_b = re.sub(r"[\s_\-]+", " ", cat_b).strip().casefold()
    if not norm_a or not norm_b:
        return 0.0
    return 1.0 if norm_a == norm_b else 0.0


def compare_dates(date_a: str, date_b: str) -> float:
    """Compare two date strings.  Simple normalised exact match for now."""
    # Strip everything except digits
    digits_a = re.sub(r"[^0-9]", "", date_a)
    digits_b = re.sub(r"[^0-9]", "", date_b)
    if not digits_a or not digits_b:
        return 0.0
    return 1.0 if digits_a == digits_b else 0.0


def compare_isbns(isbn_a: str, isbn_b: str) -> float:
    """Compare two ISBNs after normalisation.

    Handles ISBN-10 vs ISBN-13 cross-format matching: an ISBN-10 and
    its ISBN-13 equivalent (978 prefix) are treated as the same book.
    """
    norm_a = re.sub(r"[^0-9Xx]", "", isbn_a).upper()
    norm_b = re.sub(r"[^0-9Xx]", "", isbn_b).upper()
    if not norm_a or not norm_b:
        return 0.0

    # Direct match
    if norm_a == norm_b:
        return 1.0

    # Cross-format: ISBN-10 ↔ ISBN-13 (978 prefix)
    # ISBN-13 = "978" + first 9 digits of ISBN-10 + new check digit
    a10, b10 = _isbn_to_10(norm_a), _isbn_to_10(norm_b)
    if a10 and b10 and a10[:9] == b10[:9]:
        return 1.0

    return 0.0


def _isbn_to_10(isbn: str) -> str:
    """Normalise an ISBN to its 10-digit core (first 9 digits).

    For ISBN-13 starting with 978, strips the prefix and check digit.
    For ISBN-10, strips the check digit.
    Returns the 9-digit core, or empty string if not a valid length.
    """
    if len(isbn) == 13 and isbn[:3] == "978":
        return isbn[3:12]  # 9 digits after 978, before check
    elif len(isbn) == 10:
        return isbn[:9]
    return ""


# ===================================================================
# Fellegi-Sunter weight computation
# ===================================================================


def _log_odds(agreement: float, m: float, u: float) -> float:
    """Compute log-odds weight for a field comparison.

    agreement: 0.0–1.0 similarity score.
    m: P(agree | match).
    u: P(agree | non-match).

    For partial agreement, we interpolate between full-agree and
    full-disagree weights.
    """
    # Clamp to avoid log(0)
    m = max(min(m, 0.9999), 0.0001)
    u = max(min(u, 0.9999), 0.0001)

    if agreement >= 0.99:
        # Full agreement: log2(m/u)
        return math.log2(m / u)
    elif agreement <= 0.01:
        # Full disagreement: log2((1-m)/(1-u))
        return math.log2((1 - m) / (1 - u))
    else:
        # Partial agreement: linear interpolation
        w_agree = math.log2(m / u)
        w_disagree = math.log2((1 - m) / (1 - u))
        return agreement * w_agree + (1 - agreement) * w_disagree


def _log_odds_to_probability(total_log_odds: float) -> float:
    """Convert summed log-odds to a probability via sigmoid."""
    # Bayesian: posterior odds = prior odds * likelihood ratio
    # With uniform prior: P(match) = 2^w / (1 + 2^w)
    try:
        odds = 2.0 ** total_log_odds
        return odds / (1.0 + odds)
    except OverflowError:
        return 1.0 if total_log_odds > 0 else 0.0


# ===================================================================
# The matcher
# ===================================================================


class IdentityMatcher:
    """Lightweight probabilistic identity matcher with jurisdiction priors.

    Usage::

        matcher = IdentityMatcher(jurisdiction="NG")
        score = matcher.compare_records(record_a, record_b)
    """

    def __init__(self, jurisdiction: str = "default"):
        self.jurisdiction = jurisdiction
        self.priors = get_priors(jurisdiction)

    def compare_fields(
        self,
        *,
        name_a: str = "",
        name_b: str = "",
        phone_a: str = "",
        phone_b: str = "",
        national_id_a: str = "",
        national_id_b: str = "",
        email_a: str = "",
        email_b: str = "",
        address_a: Any = "",
        address_b: Any = "",
        geo_a: tuple[float, float] | None = None,
        geo_b: tuple[float, float] | None = None,
        dob_a: str = "",
        dob_b: str = "",
        isbn_a: str = "",
        isbn_b: str = "",
    ) -> MatchScore:
        """Compare two identity records field-by-field using Fellegi-Sunter.

        Returns a MatchScore with the overall probability and per-field
        factor breakdown.
        """
        total_log_odds = 0.0
        factors: dict[str, float] = {}
        parts: list[str] = []

        # Name comparison
        if name_a and name_b:
            name_sim, name_u = compare_names(name_a, name_b, self.priors)
            w = _log_odds(name_sim, self.priors.name_m, name_u)
            total_log_odds += w
            factors["name"] = round(name_sim, 4)
            if name_sim >= 0.80:
                parts.append(f"name similarity {name_sim:.0%}")

        # Phone comparison
        if phone_a and phone_b:
            phone_sim = compare_phones(phone_a, phone_b)
            w = _log_odds(phone_sim, self.priors.phone_m, self.priors.phone_u)
            total_log_odds += w
            factors["phone"] = round(phone_sim, 4)
            if phone_sim >= 0.99:
                parts.append("phone match")

        # National ID comparison
        if national_id_a and national_id_b:
            id_sim = compare_ids(national_id_a, national_id_b)
            w = _log_odds(id_sim, self.priors.national_id_m, self.priors.national_id_u)
            total_log_odds += w
            factors["national_id"] = round(id_sim, 4)
            if id_sim >= 0.99:
                parts.append("national ID match")

        # Email comparison
        if email_a and email_b:
            email_sim = compare_emails(email_a, email_b)
            w = _log_odds(email_sim, self.priors.email_m, self.priors.email_u)
            total_log_odds += w
            factors["email"] = round(email_sim, 4)
            if email_sim >= 0.99:
                parts.append("email match")

        # Address comparison
        if address_a and address_b:
            addr_sim = compare_addresses(address_a, address_b)
            w = _log_odds(addr_sim, self.priors.address_m, self.priors.address_u)
            total_log_odds += w
            factors["address"] = round(addr_sim, 4)
            if addr_sim >= 0.80:
                parts.append(f"address similarity {addr_sim:.0%}")

        # Geo comparison (lat/lon proximity — for place/facility records)
        if geo_a and geo_b:
            geo_sim = compare_geo(geo_a[0], geo_a[1], geo_b[0], geo_b[1])
            w = _log_odds(geo_sim, self.priors.geo_m, self.priors.geo_u)
            total_log_odds += w
            factors["geo"] = round(geo_sim, 4)
            if geo_sim >= 0.60:
                parts.append("nearby location")

        # Date of birth comparison
        if dob_a and dob_b:
            dob_sim = compare_dates(dob_a, dob_b)
            w = _log_odds(dob_sim, self.priors.dob_m, self.priors.dob_u)
            total_log_odds += w
            factors["dob"] = round(dob_sim, 4)
            if dob_sim >= 0.99:
                parts.append("DOB match")

        # ISBN comparison
        if isbn_a and isbn_b:
            isbn_sim = compare_isbns(isbn_a, isbn_b)
            # ISBNs are globally unique — same m/u profile as national IDs
            w = _log_odds(isbn_sim, 0.999, 0.000001)
            total_log_odds += w
            factors["isbn"] = round(isbn_sim, 4)
            if isbn_sim >= 0.99:
                parts.append("ISBN match")

        # Convert to probability
        score = _log_odds_to_probability(total_log_odds)

        # Decision
        if score >= self.priors.match_threshold:
            decision = "match"
        elif score >= self.priors.review_threshold:
            decision = "review"
        else:
            decision = "no_match"

        explanation = "; ".join(parts) if parts else "no strong signals"

        return MatchScore(
            score=round(score, 4),
            decision=decision,
            factors=factors,
            explanation=explanation,
        )


# ===================================================================
# Top-level match() function
# ===================================================================


def match(
    a: str | dict[str, str] | Any,
    b: str | dict[str, str] | Any,
    *,
    jurisdiction: str = "default",
    entity_type: str = "auto",
) -> MatchScore:
    """Compare two entities or identity records.

    Accepts strings (auto-detected type), dicts with field names, or
    Entity objects.

    Examples::

        # String comparison (auto-detects as name)
        match("Mamadou Diallo", "Mohamed Diallo")

        # String comparison with explicit type
        match("+234 801 234 5678", "08012345678", entity_type="phone")

        # Dict-based record comparison (Fellegi-Sunter)
        match(
            {"name": "Fatima Abdullahi", "phone": "+234 803 555 7890", "national_id": "12345678901"},
            {"name": "Fatoumata Abdoulaye", "phone": "08035557890"},
            jurisdiction="NG",
        )

    Parameters
    ----------
    a, b:
        The two things to compare.  Can be:
        - ``str``: compared as names (default) or by ``entity_type``.
        - ``dict``: keys are field names (name, phone, national_id, email,
          address, dob).  Compared field-by-field via Fellegi-Sunter.
        - ``Entity``: uses ``.text`` and ``.entity_type``.
    jurisdiction:
        ISO 3166-1 alpha-2 country code for jurisdiction-specific priors.
    entity_type:
        For string inputs: "auto" (default, treated as name), "name",
        "phone", "national_id", "email", "address".

    Returns
    -------
    MatchScore
        Probability, decision ("match"/"review"/"no_match"), and factors.
    """
    matcher = IdentityMatcher(jurisdiction=jurisdiction)

    # --- Both are dicts: full record comparison ---
    if isinstance(a, dict) and isinstance(b, dict):
        return matcher.compare_fields(
            name_a=a.get("name", ""),
            name_b=b.get("name", ""),
            phone_a=a.get("phone", ""),
            phone_b=b.get("phone", ""),
            national_id_a=a.get("national_id", ""),
            national_id_b=b.get("national_id", ""),
            email_a=a.get("email", ""),
            email_b=b.get("email", ""),
            address_a=a.get("address", ""),
            address_b=b.get("address", ""),
            dob_a=a.get("dob", ""),
            dob_b=b.get("dob", ""),
            isbn_a=a.get("isbn", ""),
            isbn_b=b.get("isbn", ""),
        )

    # --- Entity objects: use text + entity_type ---
    from ..extract import Entity

    if isinstance(a, Entity) and isinstance(b, Entity):
        etype = a.entity_type
        if etype in ("PERSON", "ORGANIZATION", "LOCATION"):
            return matcher.compare_fields(name_a=a.text, name_b=b.text)
        elif etype == "PHONE":
            return matcher.compare_fields(phone_a=a.text, phone_b=b.text)
        elif etype == "NATIONAL_ID":
            return matcher.compare_fields(national_id_a=a.text, national_id_b=b.text)
        elif etype == "EMAIL":
            return matcher.compare_fields(email_a=a.text, email_b=b.text)
        elif etype == "ISBN":
            return matcher.compare_fields(isbn_a=a.text, isbn_b=b.text)
        else:
            return matcher.compare_fields(name_a=a.text, name_b=b.text)

    # --- Both are strings ---
    a_str = str(a)
    b_str = str(b)

    if entity_type == "auto" or entity_type == "name":
        return matcher.compare_fields(name_a=a_str, name_b=b_str)
    elif entity_type == "phone":
        return matcher.compare_fields(phone_a=a_str, phone_b=b_str)
    elif entity_type == "national_id":
        return matcher.compare_fields(national_id_a=a_str, national_id_b=b_str)
    elif entity_type == "email":
        return matcher.compare_fields(email_a=a_str, email_b=b_str)
    elif entity_type == "address":
        return matcher.compare_fields(address_a=a_str, address_b=b_str)
    elif entity_type == "isbn":
        return matcher.compare_fields(isbn_a=a_str, isbn_b=b_str)
    else:
        return matcher.compare_fields(name_a=a_str, name_b=b_str)


# Pan-African PII Taxonomy category prefix/keyword → match() field.
def to_match_record(detections: Any) -> dict[str, Any]:
    """Build a :func:`match`-ready record dict from pipeline detections.

    Maps the first detection of each kind to the field ``match`` expects. The
    address field carries the structured detection metadata (landmark ``anchor``
    included), so a pipeline-detected address feeds resolution without being
    flattened to a string and re-parsed.

    Accepts a list of :class:`~arche.workflow.Detection`, or a
    :class:`~arche.workflow.Result` (its ``.detections`` are used).

    Example::

        result = Pipeline(jurisdiction="NG").process(text)
        record = to_match_record(result)
        match(record, other_record, jurisdiction="NG")
    """
    items = getattr(detections, "detections", detections)
    record: dict[str, Any] = {}
    for det in items:
        category = (getattr(det, "category", "") or "").upper()
        text = getattr(det, "text", "") or ""
        meta = getattr(det, "metadata", None) or {}
        if category.startswith("PII-1") and "name" not in record:
            record["name"] = text
        elif category == "PII-4-ADDRESS" and "address" not in record:
            record["address"] = {"text": text, **meta}
        elif "EMAIL" in category and "email" not in record:
            record["email"] = text
        elif category == "PII-3-PHONE" and "phone" not in record:
            record["phone"] = text
        elif "ISBN" in category and "isbn" not in record:
            record["isbn"] = text
        elif ("DOB" in category or "BIRTH" in category) and "dob" not in record:
            record["dob"] = text
        elif category.startswith("PII-2") and "national_id" not in record:
            # Category-precise: only PERSON identifier subtypes may enter
            # person-id matching. A company registration number (PII-2-RC),
            # an ambiguous tax id (TIN/KRA_PIN/TAX_REFERENCE), or an
            # unverified DID must never become `national_id` — that produced
            # false merges and person entity_ids minted from public data.
            from arche.canonical import PERSON_ID_CATEGORIES
            if category in PERSON_ID_CATEGORIES:
                record["national_id"] = text
    return record
