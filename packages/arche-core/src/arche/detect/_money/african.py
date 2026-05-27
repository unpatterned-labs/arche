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

"""African currency detection and parsing.

Detects and parses currency mentions in free text for 20+ African currencies.
Handles symbol prefixes (``₦500,000``), code prefixes (``NGN 500,000``),
word suffixes (``500,000 naira``), and common informal writing patterns.

Supported currencies include Naira, Rand, Cedi, CFA Franc (West & Central),
Kenyan/Tanzanian/Ugandan Shilling, Rwandan Franc, Ethiopian Birr,
Egyptian Pound, Moroccan Dirham, and more.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Currency specifications
# ---------------------------------------------------------------------------
# Each entry defines:
#   code        — ISO 4217 currency code
#   name        — human-readable name
#   country     — primary country (or region) of use
#   symbols     — list of symbol/prefix/suffix strings that identify this currency
#   word_names  — list of word-based identifiers (e.g. "naira", "cedi")
#   position    — "prefix" | "suffix" | "both" — where the symbol typically appears

CURRENCY_PATTERNS: dict[str, dict] = {
    "NGN": {
        "code": "NGN",
        "name": "Nigerian Naira",
        "country": "Nigeria",
        "symbols": ["₦", "NGN"],
        "prefix_symbols": ["₦", "N", "NGN"],
        "word_names": ["naira"],
        "position": "prefix",
    },
    "KES": {
        "code": "KES",
        "name": "Kenyan Shilling",
        "country": "Kenya",
        "symbols": ["KSh", "Ksh", "KES"],
        "prefix_symbols": ["KSh", "Ksh", "KES"],
        "word_names": ["kenyan shilling", "kenyan shillings", "ksh"],
        "position": "prefix",
    },
    "ZAR": {
        "code": "ZAR",
        "name": "South African Rand",
        "country": "South Africa",
        "symbols": ["ZAR", "R"],
        "prefix_symbols": ["ZAR", "R"],
        "word_names": ["rand", "rands"],
        "position": "prefix",
    },
    "GHS": {
        "code": "GHS",
        "name": "Ghanaian Cedi",
        "country": "Ghana",
        "symbols": ["GH₵", "GH¢", "GHS", "GHC"],
        "prefix_symbols": ["GH₵", "GH¢", "GHS", "GHC"],
        "word_names": ["cedi", "cedis", "ghana cedi", "ghana cedis"],
        "position": "prefix",
    },
    "XOF": {
        "code": "XOF",
        "name": "CFA Franc (West African)",
        "country": "UEMOA (Senegal, Mali, Cote d'Ivoire, Burkina Faso, Niger, Togo, Benin, Guinea-Bissau)",
        "symbols": ["FCFA", "CFA", "XOF", "F CFA"],
        "prefix_symbols": ["FCFA", "CFA", "XOF", "F CFA"],
        "word_names": ["cfa", "cfa franc", "fcfa", "franc cfa"],
        "position": "both",
    },
    "XAF": {
        "code": "XAF",
        "name": "CFA Franc (Central African)",
        "country": "CEMAC (Cameroon, CAR, Chad, Congo, Equatorial Guinea, Gabon)",
        "symbols": ["FCFA", "XAF"],
        "prefix_symbols": ["FCFA", "XAF"],
        "word_names": ["cfa", "fcfa"],
        "position": "both",
    },
    "TZS": {
        "code": "TZS",
        "name": "Tanzanian Shilling",
        "country": "Tanzania",
        "symbols": ["TSh", "TZS"],
        "prefix_symbols": ["TSh", "TZS"],
        "word_names": ["tanzanian shilling", "tanzanian shillings", "tsh"],
        "position": "prefix",
    },
    "UGX": {
        "code": "UGX",
        "name": "Ugandan Shilling",
        "country": "Uganda",
        "symbols": ["USh", "UGX"],
        "prefix_symbols": ["USh", "UGX"],
        "word_names": ["ugandan shilling", "ugandan shillings", "ush"],
        "position": "prefix",
    },
    "RWF": {
        "code": "RWF",
        "name": "Rwandan Franc",
        "country": "Rwanda",
        "symbols": ["FRw", "RWF", "RF"],
        "prefix_symbols": ["FRw", "RWF", "RF"],
        "word_names": ["rwandan franc", "rwandan francs", "frw"],
        "position": "prefix",
    },
    "ETB": {
        "code": "ETB",
        "name": "Ethiopian Birr",
        "country": "Ethiopia",
        "symbols": ["Br", "ETB"],
        "prefix_symbols": ["Br", "ETB"],
        "word_names": ["birr", "ethiopian birr"],
        "position": "prefix",
    },
    "EGP": {
        "code": "EGP",
        "name": "Egyptian Pound",
        "country": "Egypt",
        "symbols": ["E£", "EGP", "LE", "L.E."],
        "prefix_symbols": ["E£", "EGP", "LE", "L.E."],
        "word_names": ["egyptian pound", "egyptian pounds", "guineh"],
        "position": "both",
    },
    "MAD": {
        "code": "MAD",
        "name": "Moroccan Dirham",
        "country": "Morocco",
        "symbols": ["MAD", "DH", "Dhs"],
        "prefix_symbols": ["MAD"],
        "suffix_symbols": ["DH", "Dhs", "MAD"],
        "word_names": ["dirham", "dirhams", "moroccan dirham"],
        "position": "both",
    },
    "DZD": {
        "code": "DZD",
        "name": "Algerian Dinar",
        "country": "Algeria",
        "symbols": ["DZD", "DA"],
        "prefix_symbols": ["DZD"],
        "suffix_symbols": ["DA", "DZD"],
        "word_names": ["algerian dinar", "dinars"],
        "position": "both",
    },
    "TND": {
        "code": "TND",
        "name": "Tunisian Dinar",
        "country": "Tunisia",
        "symbols": ["TND", "DT"],
        "prefix_symbols": ["TND"],
        "suffix_symbols": ["DT", "TND"],
        "word_names": ["tunisian dinar"],
        "position": "both",
    },
    "CDF": {
        "code": "CDF",
        "name": "Congolese Franc",
        "country": "DR Congo",
        "symbols": ["CDF", "FC"],
        "prefix_symbols": ["CDF", "FC"],
        "word_names": ["congolese franc", "congolese francs", "franc congolais"],
        "position": "both",
    },
    "AOA": {
        "code": "AOA",
        "name": "Angolan Kwanza",
        "country": "Angola",
        "symbols": ["AOA", "Kz"],
        "prefix_symbols": ["AOA", "Kz"],
        "word_names": ["kwanza", "kwanzas"],
        "position": "prefix",
    },
    "MZN": {
        "code": "MZN",
        "name": "Mozambican Metical",
        "country": "Mozambique",
        "symbols": ["MZN", "MT"],
        "prefix_symbols": ["MZN"],
        "suffix_symbols": ["MT", "MZN"],
        "word_names": ["metical", "meticais"],
        "position": "both",
    },
    "ZMW": {
        "code": "ZMW",
        "name": "Zambian Kwacha",
        "country": "Zambia",
        "symbols": ["ZMW", "ZK"],
        "prefix_symbols": ["ZMW", "ZK"],
        "word_names": ["kwacha", "zambian kwacha"],
        "position": "prefix",
    },
    "BWP": {
        "code": "BWP",
        "name": "Botswana Pula",
        "country": "Botswana",
        "symbols": ["BWP", "P"],
        "prefix_symbols": ["BWP"],
        "word_names": ["pula", "botswana pula"],
        "position": "prefix",
    },
    "SDG": {
        "code": "SDG",
        "name": "Sudanese Pound",
        "country": "Sudan",
        "symbols": ["SDG"],
        "prefix_symbols": ["SDG"],
        "word_names": ["sudanese pound", "sudanese pounds"],
        "position": "prefix",
    },
    "SOS": {
        "code": "SOS",
        "name": "Somali Shilling",
        "country": "Somalia",
        "symbols": ["SOS", "Sh.So."],
        "prefix_symbols": ["SOS", "Sh.So."],
        "word_names": ["somali shilling", "somali shillings"],
        "position": "prefix",
    },
}


# ---------------------------------------------------------------------------
# Amount regex
# ---------------------------------------------------------------------------

# Matches numbers with optional thousands separators and decimals.
# Examples: 500000, 500,000, 500 000, 1,500.50, 1.500,50 (European style)
_AMOUNT_PATTERN = r"(\d{1,3}(?:[,.\s]\d{3})*(?:[.,]\d{1,2})?)"

# Build a combined regex for all known prefix symbols.
# We sort by length descending so longer symbols match first (e.g., "GH₵" before "G").
_ALL_PREFIX_SYMBOLS: list[str] = []
_SYMBOL_TO_CURRENCY: dict[str, str] = {}

for _code, _spec in CURRENCY_PATTERNS.items():
    for sym in _spec.get("prefix_symbols", []):
        if sym not in _SYMBOL_TO_CURRENCY:
            _ALL_PREFIX_SYMBOLS.append(sym)
            _SYMBOL_TO_CURRENCY[sym] = _code
        # If ambiguous (e.g., "FCFA" for XOF and XAF), first registration wins.
        # XOF is registered before XAF so West African CFA takes priority.

# Sort longest first for regex alternation priority
_ALL_PREFIX_SYMBOLS.sort(key=len, reverse=True)

# Build suffix symbols similarly
_ALL_SUFFIX_SYMBOLS: list[str] = []
_SUFFIX_TO_CURRENCY: dict[str, str] = {}
for _code, _spec in CURRENCY_PATTERNS.items():
    for sym in _spec.get("suffix_symbols", []):
        if sym not in _SUFFIX_TO_CURRENCY:
            _ALL_SUFFIX_SYMBOLS.append(sym)
            _SUFFIX_TO_CURRENCY[sym] = _code
_ALL_SUFFIX_SYMBOLS.sort(key=len, reverse=True)

# Build word names
_ALL_WORD_NAMES: list[str] = []
_WORD_TO_CURRENCY: dict[str, str] = {}
for _code, _spec in CURRENCY_PATTERNS.items():
    for wn in _spec.get("word_names", []):
        if wn not in _WORD_TO_CURRENCY:
            _ALL_WORD_NAMES.append(wn)
            _WORD_TO_CURRENCY[wn] = _code
_ALL_WORD_NAMES.sort(key=len, reverse=True)


def _escape_for_regex(s: str) -> str:
    """Escape a string for use in a regex alternation."""
    return re.escape(s)


def _build_prefix_regex() -> re.Pattern:
    """Build regex: SYMBOL [optional space] AMOUNT."""
    symbols_alt = "|".join(_escape_for_regex(s) for s in _ALL_PREFIX_SYMBOLS)
    return re.compile(
        rf"(?<![A-Za-z0-9])"
        rf"({symbols_alt})"
        rf"\s*"
        rf"{_AMOUNT_PATTERN}"
        rf"(?![0-9])",
        re.IGNORECASE,
    )


def _build_suffix_regex() -> re.Pattern:
    """Build regex: AMOUNT [optional space] SYMBOL."""
    symbols_alt = "|".join(_escape_for_regex(s) for s in _ALL_SUFFIX_SYMBOLS)
    return re.compile(
        rf"(?<![0-9])"
        rf"{_AMOUNT_PATTERN}"
        rf"\s*"
        rf"({symbols_alt})"
        rf"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _build_word_regex() -> re.Pattern:
    """Build regex: AMOUNT [optional space] WORD_NAME."""
    words_alt = "|".join(_escape_for_regex(w) for w in _ALL_WORD_NAMES)
    return re.compile(
        rf"(?<![0-9])"
        rf"{_AMOUNT_PATTERN}"
        rf"\s+"
        rf"({words_alt})"
        rf"(?![A-Za-z])",
        re.IGNORECASE,
    )


_PREFIX_RE = _build_prefix_regex()
_SUFFIX_RE = _build_suffix_regex()
_WORD_RE = _build_word_regex()


def _parse_amount(raw: str) -> float:
    """Parse a raw amount string to a float.

    Handles:
    - ``500,000`` → 500000.0
    - ``500 000`` → 500000.0
    - ``1,500.50`` → 1500.50
    - ``1.500,50`` → 1500.50 (European/French style common in francophone Africa)
    """
    cleaned = raw.strip()

    # Detect European-style: if last separator is a comma and has <=2 digits after
    # e.g. "1.500,50"
    if "," in cleaned and "." in cleaned:
        last_comma = cleaned.rfind(",")
        last_dot = cleaned.rfind(".")
        if last_comma > last_dot:
            # European: dots are thousands, comma is decimal
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Anglo: commas are thousands, dot is decimal
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Could be thousands separator or decimal
        after_comma = cleaned.split(",")[-1]
        if len(after_comma) <= 2:
            # Treat as decimal (e.g. "500,50")
            cleaned = cleaned.replace(",", ".")
        else:
            # Treat as thousands separator (e.g. "500,000")
            cleaned = cleaned.replace(",", "")
    elif " " in cleaned:
        # Space as thousands separator
        cleaned = cleaned.replace(" ", "")

    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_african_currency(text: str) -> list[dict]:
    """Detect African currency mentions in free text.

    Scans for prefix-symbol patterns (``₦500,000``), suffix-symbol patterns
    (``1,000 DH``), and word-based patterns (``500,000 naira``).

    Parameters
    ----------
    text:
        Input text to scan.

    Returns
    -------
    list[dict]
        Each dict contains:
        - ``currency`` — ISO 4217 code (e.g. ``"NGN"``)
        - ``currency_name`` — human-readable (e.g. ``"Nigerian Naira"``)
        - ``amount`` — parsed float value
        - ``raw_amount`` — the original amount string
        - ``raw`` — the full matched text
        - ``start`` / ``end`` — character offsets

    Examples
    --------
    >>> detect_african_currency("The total is ₦500,000 or KSh 50,000")
    [{'currency': 'NGN', 'amount': 500000.0, ...}, {'currency': 'KES', 'amount': 50000.0, ...}]
    >>> detect_african_currency("Price: 1,500.50 DH")
    [{'currency': 'MAD', 'amount': 1500.5, ...}]
    """
    results: list[dict] = []
    seen_spans: set[tuple[int, int]] = set()

    # 1) Prefix matches: SYMBOL AMOUNT
    for m in _PREFIX_RE.finditer(text):
        span = (m.start(), m.end())
        if any(_overlaps(span, s) for s in seen_spans):
            continue

        symbol = m.group(1)
        raw_amount = m.group(2)
        currency_code = _SYMBOL_TO_CURRENCY.get(symbol)
        if not currency_code:
            # Try case-insensitive lookup
            for k, v in _SYMBOL_TO_CURRENCY.items():
                if k.lower() == symbol.lower():
                    currency_code = v
                    break
        if currency_code:
            spec = CURRENCY_PATTERNS[currency_code]
            results.append({
                "currency": currency_code,
                "currency_name": spec["name"],
                "amount": _parse_amount(raw_amount),
                "raw_amount": raw_amount,
                "raw": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
            seen_spans.add(span)

    # 2) Suffix matches: AMOUNT SYMBOL
    for m in _SUFFIX_RE.finditer(text):
        span = (m.start(), m.end())
        if any(_overlaps(span, s) for s in seen_spans):
            continue

        raw_amount = m.group(1)
        symbol = m.group(2)
        currency_code = _SUFFIX_TO_CURRENCY.get(symbol)
        if not currency_code:
            for k, v in _SUFFIX_TO_CURRENCY.items():
                if k.lower() == symbol.lower():
                    currency_code = v
                    break
        if currency_code:
            spec = CURRENCY_PATTERNS[currency_code]
            results.append({
                "currency": currency_code,
                "currency_name": spec["name"],
                "amount": _parse_amount(raw_amount),
                "raw_amount": raw_amount,
                "raw": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
            seen_spans.add(span)

    # 3) Word matches: AMOUNT word_name
    for m in _WORD_RE.finditer(text):
        span = (m.start(), m.end())
        if any(_overlaps(span, s) for s in seen_spans):
            continue

        raw_amount = m.group(1)
        word = m.group(2).lower()
        currency_code = _WORD_TO_CURRENCY.get(word)
        if currency_code:
            spec = CURRENCY_PATTERNS[currency_code]
            results.append({
                "currency": currency_code,
                "currency_name": spec["name"],
                "amount": _parse_amount(raw_amount),
                "raw_amount": raw_amount,
                "raw": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
            seen_spans.add(span)

    # Sort by position in text
    results.sort(key=lambda x: x["start"])
    return results


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Return True if two (start, end) spans overlap."""
    return a[0] < b[1] and b[0] < a[1]
