# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Product code and specification evidence, organised by category.

There is no "model number" signal
---------------------------------
Measured on the Leipzig Abt-Buy benchmark (1,081 x 1,092, complete ground
truth), a regex that extracts code-looking tokens from a product title blocks
1,384 candidate pairs at **0.5643** precision. That looks like a weak signal.
Conditioned on how *rare* the shared code is, it separates almost perfectly:

    rarest shared code, document frequency   pairs   true   precision
    1-2                                        754    752      0.9973
    3-4                                         47     23      0.4894
    5-9                                         55      6      0.1091
    10-19                                       25      0      0.0000
    20+                                        503      0      0.0000

503 candidate pairs share a code seen twenty or more times — ``1080p``,
``16gb``, ``720p`` — and **not one is a true match**. So the identifying signal
is not "looks like a model number", it is "is rare". ``1080p`` is the
``General Hospital`` of consumer electronics, and the fix is the same one the
place lane already ships: a frequency table and the distinctiveness gate, not a
cleverer regex and a hand-maintained blocklist of spec words.

That is why :func:`build_code_table` exists and why :func:`compare_codes` takes
a table. Without one it can only say "these share a code", which the numbers
above show is barely better than a coin flip.

Why the table is self-calibrated
--------------------------------
It is built from the two catalogues being matched rather than shipped in the
wheel. That is not training on the test set — it is estimating document
frequency over the data at hand, which is where Fellegi-Sunter u-probabilities
come from. It also sidesteps a licensing problem: no open product catalogue we
could ship carries a licence in ``OPEN_LICENCE_CLASSES``.

Categories, and why this is a registry
--------------------------------------
What counts as a code and which specifications carry identity are properties of
a *product category*, not of products. An electronics title exposes a
manufacturer model code; a grocery item is brand plus net contents; a book is an
ISBN plus an edition; apparel is style plus size, where ``501`` is the model and
``32x32`` is not. A rule fitted to electronics fails on all three — Levi's
``501`` is excluded by a length threshold that exists to reject prices, and
``600mg`` would be read as a model code for a drug.

So categories register their own rules and share the machinery.
:func:`register_category` is the extension point for food, books and apparel.
Only ``electronics`` ships today, and it ships marked experimental, because one
vertical is the evidence base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from arche.resolve._matcher import _normalise_id, _normalise_text
from arche.resolve._tokenfreq import TokenFrequencyTable

__all__ = [
    "code_rarity",
    "PRODUCT_CATEGORIES",
    "ProductCategory",
    "build_code_table",
    "compare_codes",
    "compare_specs",
    "extract_product_code_candidates",
    "extract_specs",
    "register_category",
]

# A token that could be a product code: starts alphanumeric, may carry internal
# hyphens or slashes. Deliberately permissive — the frequency table, not this
# pattern, decides what is identifying.
_CODE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]{2,}")

# A number bound to a unit: `16GB`, `5.7 cu.ft`, `120 Hz`, `12-pack`, `600mg`.
# The left boundary is load-bearing. Without it the number is carved out of a
# model code: `F5C400300W` read as 400,300 watts and `WNR3500L` as 3,500 litres.
# 27.4% of identity-unit matches on Abt-Buy were fabricated that way, and one
# true pair (`F5C400300W` against `F5C400-300W`, the same product) was refuted
# for a 400,300W-vs-300W "disagreement".
#
# Bare `in` is excluded deliberately: it fires inside `3-in-1`, turning a
# charger's form factor into 3 inches, so `3-in-1` and `5-in-1` "disagreed".
# `inch`, `"` and `'` carry that unit instead.
_SPEC = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*-?\s*"
    r"(gb|tb|mb|kb|mp|mhz|ghz|hz|wh|mah|mm|cm|ft|inch|oz|lb|kg|ml|ct|pk|pack|w|v|p)"
    r"(?![a-z0-9])",
    re.I,
)

# Unit spellings that mean the same thing. Kept tiny and explicit: a large
# synonym table here would be a lexicon pretending to be a parser.
_UNIT_ALIASES = {"pk": "pack"}
_UNIT_SCALE: dict[str, float] = {}


@dataclass(frozen=True)
class ProductCategory:
    """Rules for reading identity out of one category's titles.

    ``identity_units`` is the part that encodes the **identity contract**: which
    specifications distinguish two purchasable variants. Under a SKU contract a
    16GB and a 32GB player are different products, so ``gb`` is identity-bearing
    and a disagreement refutes. Under a product-family contract it would not be.
    Changing this tuple changes what the lane means, which is why it is data on
    a category rather than a constant in a comparator.
    """

    name: str
    #: Minimum length of a normalised code candidate.
    min_code_len: int = 4
    #: Reject bare numbers shorter than this (prices, years, quantities).
    min_bare_number_len: int = 5
    #: Units whose disagreement means "different purchasable variant".
    identity_units: tuple[str, ...] = ()
    #: Substrings that never identify, whatever their frequency.
    stop_codes: frozenset[str] = field(default_factory=frozenset)
    experimental: bool = True


PRODUCT_CATEGORIES: dict[str, ProductCategory] = {}


def register_category(category: ProductCategory) -> None:
    """Register a product category's rules. The extension point for new lanes.

    Adding food, books or apparel is a category registration plus a benchmark,
    not a change to any comparator.
    """
    PRODUCT_CATEGORIES[category.name] = category


register_category(ProductCategory(
    name="electronics",
    identity_units=("gb", "tb", "mb", "inch", "mp", "ghz", "mhz", "mah", "v", "w"),
    # `1080p` and `720p` are resolutions shared by thousands of products. The
    # frequency table already suppresses them; naming them here means a small
    # catalogue, where every code looks rare, does not merge on a resolution.
    stop_codes=frozenset({"1080p", "720p", "480p", "1080i", "4k", "8k"}),
    experimental=True,
))


def _category(name: str | None) -> ProductCategory:
    if not name:
        return PRODUCT_CATEGORIES["electronics"]
    try:
        return PRODUCT_CATEGORIES[name]
    except KeyError:
        raise ValueError(
            f"unknown product category {name!r}; registered: "
            f"{sorted(PRODUCT_CATEGORIES)}"
        ) from None


def extract_product_code_candidates(
    text: str, category: str | None = None,
) -> set[str]:
    """Normalised code *candidates* from a product title.

    Candidates, not model numbers — the name is deliberate. This returns every
    token that could be a manufacturer code, a retailer SKU, a spec or a
    quantity, because a regex cannot tell them apart. Rarity does that, later.

    ``Fellowes Powershred SB-97Cs Shredder - 3219701`` yields ``{'sb97cs',
    '3219701'}``. Normalisation is what makes the signal work at all: matching
    on raw strings finds a shared code on 44.9% of true pairs, and on normalised
    strings 71.2%, because one source writes ``SB97CS`` and the other
    ``SB-97Cs``.

    Each candidate span is normalised individually, never the whole title, so
    two adjacent codes cannot fuse into one that neither source wrote.
    """
    cat = _category(category)
    out: set[str] = set()
    for raw in _CODE_TOKEN.findall((text or "")[:_MAX_TITLE_CHARS]):
        norm = _normalise_id(raw)
        if len(norm) < cat.min_code_len:
            continue
        if not any(c.isdigit() for c in norm):
            continue
        if norm.isdigit() and len(norm) < cat.min_bare_number_len:
            continue
        if norm in cat.stop_codes:
            continue
        out.add(norm)
    return out


# Product titles are short. A field far longer than this is malformed input or
# a scraped page body, and the cost of normalising it is real: 10,000 characters
# of NFKD plus per-codepoint category lookups measured at 5.6 seconds, against
# 0.5 milliseconds for a realistic title. The regexes themselves are linear —
# this is a bound on unbounded input, not a backtracking fix.
_MAX_TITLE_CHARS = 2000


def extract_specs(text: str, category: str | None = None) -> dict[str, set[float]]:
    """Numeric specifications as ``{unit: {values}}``.

    ``Sony 16GB 1080p 3.5 inch player`` gives ``{'gb': {16.0}, 'p': {1080.0},
    'inch': {3.5}}``. A unit can hold several values because titles list several
    ("5.7 Cu.Ft. 27 inch").
    """
    _category(category)
    out: dict[str, set[float]] = {}
    for num, unit in _SPEC.findall(_normalise_text((text or "")[:_MAX_TITLE_CHARS])):
        u = unit.lower()
        value = float(num) * _UNIT_SCALE.get(u, 1.0)
        u = _UNIT_ALIASES.get(u, u)
        out.setdefault(u, set()).add(value)
    return out


def build_code_table(
    texts: Iterable[str], category: str | None = None,
) -> TokenFrequencyTable:
    """A document-frequency table over code candidates, built from the corpus.

    Feed it every title from **both** lists being matched. The result is what
    turns a 0.5643-precision block into a 0.9973-precision one, by telling
    ``compare_codes`` that ``2595b002`` appears twice and ``16gb`` appears
    eleven times.
    """
    docs = (
        " ".join(sorted(extract_product_code_candidates(t, category)))
        for t in texts
    )
    table = TokenFrequencyTable.from_corpus(d for d in docs if d)
    # What a code that identifies exactly one product looks like *here*. A
    # shared code spans both sides of a pair, so the floor is 2; redundant
    # catalogues push it up. The 10th percentile is used rather than the
    # minimum so a single anomalous code cannot set the scale.
    # A code identifying exactly one product appears once per side, so the
    # baseline is 2 in a catalogue with no duplicate listings. When every
    # product is listed k times it becomes 2k, and the median df across codes
    # estimates k directly: most codes belong to one product, so their df is
    # the redundancy factor. Anchoring on the constant 2 instead made recall
    # collapse from 0.6645 to 0.0419 on a merely-redundant catalogue, because
    # a unique code scored 2/4 and fell under the gate floor.
    dfs = sorted((getattr(table, "_counts", None) or {}).values())
    median_df = dfs[len(dfs) // 2] if dfs else 1.0
    table.code_baseline_df = max(2.0, 2.0 * median_df)
    return table


def compare_codes(
    text_a: str,
    text_b: str,
    tf: TokenFrequencyTable | None = None,
    category: str | None = None,
) -> float | None:
    """Rarity-weighted agreement on product codes, or ``None`` if neither side has any.

    Returns the distinctiveness of the **rarest shared** candidate, so agreement
    on a code nobody else uses scores near 1.0 while agreement on ``16gb``
    scores near 0.0 — which is what the measurement says those two facts are
    worth.

    Without a ``tf`` this degrades to a plain 1.0/0.0 on any shared code. That
    is the 0.5643-precision behaviour, and it is the reason the shipped pack
    builds a table.

    ``None`` when either side yields no candidate at all: absent evidence
    refutes nothing, the same rule ``veto_km`` and the ``qualifier`` comparator
    already follow. Codes present on both sides but not shared score 0.0 rather
    than ``None`` — that is a disagreement, and it is left to ``weight`` rather
    than made a veto, because 18.6% of true pairs disagree this way (accessories,
    bundles, retailer SKUs).
    """
    ca = extract_product_code_candidates(text_a, category)
    cb = extract_product_code_candidates(text_b, category)
    if not ca or not cb:
        return None
    shared = ca & cb
    if not shared:
        return 0.0
    if tf is None:
        return 1.0
    return max(code_rarity(code, tf) for code in shared)


def code_rarity(code: str, tf: TokenFrequencyTable) -> float:
    """How identifying a shared code is, from its document frequency.

    Deliberately **not** ``TokenFrequencyTable.distinctiveness``. That measure
    is ``min(1, -log10(rel_freq) / 5)``, calibrated for the million-token word
    corpora the place and person tables are built from. A code vocabulary is
    tiny — Abt-Buy yields about 2,000 documents — so the rarest possible shared
    code, appearing exactly once in each source, scores 0.6205 through it. That
    is below ``DISTINCTIVE_FLOOR`` (0.75), so the gate demoted **every** true
    product match and recall fell from 0.2197 to 0.0948. The formula was not
    wrong, it was being asked a question about a different distribution.

    Document frequency answers it directly, and the shape here is the measured
    precision curve rather than a guess:

        df 1-2   precision 0.9973   ->  1.0
        df 3-4             0.4894   ->  0.67 / 0.50
        df 5-9             0.1091   ->  0.40 / 0.22
        df 20+             0.0000   ->  0.10

    A shared code has df >= 2 by construction — one document from each side —
    so ``2 / df`` puts the best case at exactly 1.0 and decays from there.
    """
    counts = getattr(tf, "_counts", None) or {}
    df = counts.get(code, 0.0)
    if df <= 0:
        return 1.0  # unseen in the table: as rare as it gets
    # Relative to what "unique" looks like in THIS corpus, not to the constant
    # 2 that a single-listing catalogue happens to produce. A catalogue where
    # every product is listed twice gives a unique code df=4, and scoring that
    # against a hardcoded 2 put it at 0.5 — below the gate floor — so recall
    # collapsed from 0.6645 to 0.0419 on a corpus that was merely redundant.
    baseline = getattr(tf, "code_baseline_df", 0.0) or 2.0
    return min(1.0, baseline / df)


def compare_specs(
    text_a: str, text_b: str, category: str | None = None,
) -> float | None:
    """Agreement on identity-bearing specifications, or ``None`` if not comparable.

    Only units in the category's ``identity_units`` are consulted, and only when
    both titles carry the same unit. Returns 1.0 when every comparable unit
    shares a value and 0.0 when any disagrees.

    Pair it with ``refutes_below`` under a SKU identity contract: a 16GB player
    and a 32GB player are different purchasable products however alike their
    titles. On Abt-Buy, 46 of 46 true pairs carrying a comparable unit agree on
    every one of them, so the refutation costs nothing measurable there — but 46
    is a thin evidence base and it is reported as such.
    """
    cat = _category(category)
    sa, sb = extract_specs(text_a, category), extract_specs(text_b, category)
    units = {u for u in (set(sa) & set(sb)) if u in cat.identity_units}
    if not units:
        return None
    return 1.0 if all(sa[u] & sb[u] for u in units) else 0.0
