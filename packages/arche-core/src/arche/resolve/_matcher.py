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
from dataclasses import dataclass, field
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
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
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


def compare_addresses(addr_a: str, addr_b: str) -> float:
    """Compare two addresses using string similarity.

    Future: spatial proximity via geocoding, landmark matching.
    """
    norm_a = _normalise_text(addr_a)
    norm_b = _normalise_text(addr_b)
    if not norm_a or not norm_b:
        return 0.0

    if norm_a == norm_b:
        return 1.0

    # Token-sort handles word reordering ("Ikeja Lagos" vs "Lagos Ikeja")
    ts = _token_sort_ratio(norm_a, norm_b)

    # Jaro-Winkler for character-level similarity
    jw = _jaro_winkler(norm_a, norm_b)

    return max(ts, jw)


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
        address_a: str = "",
        address_b: str = "",
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
