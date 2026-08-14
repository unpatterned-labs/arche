# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Product code and specification evidence, organised by category.

There is no "model number" signal
---------------------------------
Measured on the Leipzig Abt-Buy benchmark (1,081 x 1,092, complete ground
truth), with the rules this module actually ships:

    code-blocking alone                       881 pairs, precision 0.8865
    + rarity filter (code_rarity >= 0.75)     754 pairs, precision 0.9973

(Both over the full cross-product. Inside the union blocker's own candidate
set the same two rows are 856/0.8843 and 731/0.9973 — a different population,
never to be mixed into one series.)

**The frequency table does that work, not the stop list.** Two earlier versions
of this docstring got the attribution wrong in opposite directions, so here is
the end-to-end measurement rather than an argument. Abt-Buy, shipped pack,
``stop_codes`` on against ``stop_codes`` emptied:

    stop_codes ON  (shipped)   TP 728  FP 22  P 0.9707  R 0.6636
    stop_codes DISABLED        TP 728  FP 22  P 0.9707  R 0.6636

Byte-identical. On this benchmark the stop list contributes **nothing**, because
the table already scores ``1080p`` far below the gate: at df 11, ``16gb`` is
0.182 against 1.0 for a code seen about as often as a unique one, and only the
latter clears ``DISTINCTIVE_FLOOR`` unaided.

What the stop list *does* earn is the small-catalogue case, which the benchmark
cannot show. In a catalogue of four records where the only shared code is a
resolution, every code looks rare and the table cannot tell them apart —
``stop_codes`` off gives two false merges there, on gives none. It is a floor
for corpora too small to estimate frequency from, not a substitute for
estimating it.

(For completeness, since the figure has been quoted: with ``stop_codes``
disabled the *unfiltered candidate block* is 0.5643 over 1,384 pairs, because a
bucket of 503 pairs sharing a code seen 20+ times enters and contains no true
match. That is a statement about the block, not about the lane's output, and the
rarity filter reaches 0.9973 either way.)

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
    "build_brand_prefixes",
    "code_rarity",
    "strip_brand_prefix",
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
# Alternation is leftmost-first, so two-letter units MUST precede the bare `g`
# and `l` — otherwise `415g` is fine but `2kg` matches `g` and reports 2 grams.
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
    r"(gb|tb|mb|kb|mp|mhz|ghz|hz|wh|mah|mg|kg|mm|cm|ft|inch|oz|lb|ml|ct|pk|pack|g|l|w|v|p)"
    r"(?![a-z0-9])",
    re.I,
)

# Unit spellings that mean the same thing. Kept tiny and explicit: a large
# synonym table here would be a lexicon pretending to be a parser.
# A candidate that is nothing but a number and a unit.
_QUANTITY_ONLY = re.compile(
    r"\d+(?:gb|tb|mb|kb|mp|mhz|ghz|hz|wh|mah|mg|kg|mm|cm|ft|inch|oz|lb|ml|ct|pk|pack|g|l|w|v|p)"
)

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
    #: Treat a bare number+unit token (`415g`, `600mg`) as a specification
    #: rather than a code candidate.
    #:
    #: Opt-in per category, not global. Groceries and pharmacy need it — reading
    #: a dose as a model number is the failure this exists to prevent. Consumer
    #: electronics does not: `16gb` is a legitimate code candidate there, the
    #: frequency table already scores it 0.182, and switching this on for
    #: electronics moved a published Abt-Buy figure by one true match for no
    #: benefit at all.
    quantities_are_specs: bool = False
    experimental: bool = True


PRODUCT_CATEGORIES: dict[str, ProductCategory] = {}


def register_category(category: ProductCategory, *, replace: bool = False) -> None:
    """Register a product category's rules. The extension point for new lanes.

    Adding food, books or apparel is a category registration plus a benchmark,
    not a change to any comparator.

    Re-registering an existing name raises unless ``replace=True``. Silently
    overwriting is a process-wide change to how every caller reads product
    titles — re-registering ``electronics`` with a longer minimum code length
    makes ``extract_product_code_candidates`` return nothing, everywhere, with
    no error. Deliberate replacement is fine; accidental shadowing is not.
    """
    existing = PRODUCT_CATEGORIES.get(category.name)
    if existing is not None and not replace and existing != category:
        raise ValueError(
            f"product category {category.name!r} is already registered; pass "
            "replace=True if you mean to change it process-wide"
        )
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


register_category(ProductCategory(
    name="food",
    # Net contents are the identity of a grocery SKU, and today the electronics
    # rules read them as *codes*: `Heinz Baked Beans 415g` yields the candidate
    # `415g`, and `Mucinex DM 600mg 20ct` yields `600mg` and `20ct`. Treating a
    # dose as a model number is the failure an adversarial review of this lane
    # called out by name, and it is the current behaviour if anyone points
    # `product_electronics` at a grocery catalogue.
    #
    # This category exists primarily to stop that. Quantities become
    # identity-bearing *specifications* — where a disagreement refutes under the
    # purchasable-variant contract — instead of identifying codes.
    #
    # NO MATCHING BENCHMARK. Its extraction behaviour is tested; its matching
    # accuracy is not, because no open grocery corpus with complete ground truth
    # is available to this project. Do not read it as measured. The gate for
    # promoting it out of this state is a labelled corpus, the same bar the
    # electronics lane had to clear.
    identity_units=("g", "kg", "ml", "l", "oz", "lb", "ct", "pack", "mg"),
    quantities_are_specs=True,
    # A GTIN/EAN is 8-14 digits and is the real identifier when present, so bare
    # numbers below that stay excluded while the barcode itself survives.
    min_bare_number_len=8,
    stop_codes=frozenset({"organic", "family", "value"}),
    experimental=True,
))

register_category(ProductCategory(
    name="bibliographic",
    # Papers, articles and books. The identifying code is an ISBN, a DOI or an
    # arXiv id — long, checksummed where it matters, and genuinely rare — so the
    # length floor rises and specification units are irrelevant.
    #
    # Measured on Leipzig DBLP-ACM (2,616 x 2,294, complete ground truth):
    # P=0.9506, R=0.9960 with the `bibliographic` pack. That corpus is
    # *papers*, not books, so ISBN handling here is correct but unmeasured.
    min_code_len=8,
    min_bare_number_len=8,
    identity_units=(),
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
        if cat.quantities_are_specs and _QUANTITY_ONLY.fullmatch(norm):
            # `415g`, `600mg`, `12pack` are net contents, not identifiers. For a
            # category that declares them identity-bearing they belong to
            # `extract_specs`, where a disagreement refutes — reading a drug's
            # dose as a model code is the failure this split exists to prevent.
            continue
        out.add(norm)
    return out


# Product titles are short. A field far longer than this is malformed input or
# a scraped page body, and the cost of normalising it is real: 10,000 characters
# of NFKD plus per-codepoint category lookups measured at 5.6 seconds, against
# 0.5 milliseconds for a realistic title. The regexes themselves are linear —
# this is a bound on unbounded input, not a backtracking fix.
_MAX_TITLE_CHARS = 2000

#: Distinct codes needed before the redundancy warning is meaningful. The
#: statistic behind it is a quartile, and a quartile over a handful of codes is
#: noise: the four-record catalogue in the test suite reported a "typical"
#: document frequency of 4 purely because its only shared token appeared in
#: every record.
_MIN_VOCAB_FOR_REDUNDANCY_WARNING = 20


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
    turns a 0.8865-precision block into a 0.9973-precision one, by telling
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
    # collapse from 0.6636 to 0.0419 on a merely-redundant catalogue, because
    # a unique code scored 2/4 and fell under the gate floor.
    # The 25th percentile, not the median: most codes in a healthy catalogue
    # identify one product, so the lower quartile tracks the redundancy factor
    # while staying robust to a vocabulary dominated by a few common codes. A
    # median over a two-code vocabulary is 50% noise.
    dfs = sorted(table._as_counts().values())
    typical = dfs[len(dfs) // 4] if dfs else 1.0
    table.code_baseline_df = max(2.0, 2.0 * typical)

    # An applicability bound, said out loud. This whole lane was measured on
    # catalogues where a product code appears once per side. The baseline
    # adapts to redundancy, but it is estimated, and a catalogue where the
    # typical code already appears many times is outside what has been tested.
    #
    # Gated on vocabulary size, because `typical` is a quartile and a quartile
    # over a handful of codes is not a statistic. A four-record catalogue whose
    # only shared token is `1080p` yields a "typical" of 4 and warned about
    # redundancy that does not exist — a warning that fires on toy inputs is
    # how people learn to ignore warnings.
    if len(dfs) >= _MIN_VOCAB_FOR_REDUNDANCY_WARNING and typical > 2:
        import warnings

        warnings.warn(
            f"product code table: the typical code appears {typical:g} times, "
            "so this catalogue carries more redundancy than the lane was "
            "measured on (once per source). Rarity is estimated relative to "
            "that baseline and the lane's published accuracy does not "
            "necessarily hold — check a labelled sample before trusting "
            "auto-matches.",
            UserWarning,
            stacklevel=2,
        )
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
    is the 0.8865-precision behaviour, and it is the reason the shipped pack
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
        # Fail loud, like `tftoken` does in the same situation. Without a table
        # this returns 1.0 for `16gb` exactly as for `2595b002`, which drops
        # block precision from 0.9973 to 0.8865 and looks like nothing is
        # wrong. A silently worse answer is the failure mode worth refusing.
        raise ValueError(
            "comparator kind 'code' requires a frequency table over code "
            "candidates; build one with "
            "arche.resolve._productcode.build_code_table(titles). "
            "reconcile()/crosswalk() build it for you when a 'code' comparator "
            "is declared."
        )
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

    Document frequency answers it directly, and the shape here is a measured
    precision curve rather than a guess. It was measured with ``stop_codes``
    disabled, which is what produces a df-20+ bucket at all — with the shipped
    stop list the maximum df is 11. The curve's *shape* is what this function
    borrows, not its absolute precisions:

        df 1-2   precision 0.9973   ->  1.0
        df 3-4             0.4894   ->  0.67 / 0.50
        df 5-9             0.1091   ->  0.40 / 0.22
        df 20+             0.0000   ->  0.10

    A shared code has df >= 2 by construction — one document from each side —
    so ``2 / df`` puts the best case at exactly 1.0 and decays from there.
    """
    # `_as_counts()` rather than `_counts`: a table built from relative
    # frequencies alone carries `_counts = None`, and reading the attribute
    # directly made *every* code score 1.0 — maximally rare, silently. That is
    # worse than a crash, because the run looks like it worked.
    df = tf._as_counts().get(code, 0.0)
    if df <= 0:
        return 1.0  # unseen in the table: as rare as it gets
    # Relative to what "unique" looks like in THIS corpus, not to the constant
    # 2 that a single-listing catalogue happens to produce. A catalogue where
    # every product is listed twice gives a unique code df=4, and scoring that
    # against a hardcoded 2 put it at 0.5 — below the gate floor — so recall
    # collapsed from 0.6636 to 0.0419 on a corpus that was merely redundant.
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
    titles. On Abt-Buy, 47 of 47 true pairs carrying a comparable unit agree on
    every one of them, so the refutation costs nothing measurable there — but 47
    of 1,097 is a thin evidence base and it is reported as such. Its measured
    effect on Abt-Buy is **exactly nothing** — identical precision, recall and
    counts with and without it — and on Amazon-GoogleProducts the comparator is
    entirely inert, because no true pair there carries a comparable unit. It
    earns its place from the identity contract, not from either corpus, and
    `test_the_spec_refutation_is_neutral_on_the_benchmark` pins that so a change
    making it *harmful* is caught.
    """
    cat = _category(category)
    sa, sb = extract_specs(text_a, category), extract_specs(text_b, category)
    units = {u for u in (set(sa) & set(sb)) if u in cat.identity_units}
    if not units:
        return None
    return 1.0 if all(sa[u] & sb[u] for u in units) else 0.0


def build_brand_prefixes(values: Iterable[str], *, min_length: int = 4) -> frozenset[str]:
    """Brand or publisher names, from a corpus's own manufacturer column.

    Self-calibrated for the same reason the code table is: the vocabulary that
    matters is the one in the catalogues being matched, and no shippable list
    would cover them.

    ``min_length`` rejects initialisms short enough to appear inside ordinary
    titles — a two-character "brand" would strip the front off half the corpus.
    """
    return frozenset(
        cleaned for value in values
        if len(cleaned := str(value or "").strip().lower()) >= min_length
    )


def strip_brand_prefix(name: str, brands: frozenset[str]) -> tuple[str, str]:
    """Split a leading brand off a product title: ``(core, brand)``.

    One source prefixes the publisher and the other does not, which is the same
    representation mismatch the place lane hit with trailing region qualifiers::

        Amazon   'swat 4: special weapons and tactics'
        Google   'vivendi-universal games inc swat 4'

    Measured on Amazon-GoogleProducts, where 42% of Google titles carry such a
    prefix, removing it moves F1 from 0.3971 to 0.4275 — and unusually, both
    precision (0.4898 -> 0.5327) and recall (0.3338 -> 0.3569) improve, because
    the prefix was simultaneously diluting true agreement and manufacturing
    false agreement between unrelated products from one publisher.

    The longest matching brand wins, so ``electronic arts inc`` beats
    ``electronic arts``. A title that is *only* a brand is returned unchanged —
    stripping it would leave nothing to match on.
    """
    text = (name or "").strip()
    lowered = text.lower()
    best = ""
    for brand in brands:
        if lowered.startswith(brand) and len(brand) > len(best):
            best = brand
    if not best:
        return text, ""
    core = text[len(best):].strip(" -,:|")
    if not core:
        return text, ""
    return core, text[:len(best)]
