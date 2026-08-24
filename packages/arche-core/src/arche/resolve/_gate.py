# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shared distinctive-signal gate toolkit.

The primitives BOTH resolve engines' gates are built from — deliberately *not*
one merged gate. The two engines keep distinct combination laws and distinct
gate policies for good reasons:

* ``reconcile`` (list crosswalk): weighted-mean score; its gate clears when any
  distinctive-KIND comparator similarity reaches the floor.
* ``coref`` (pairwise): Fellegi-Sunter log-odds; its gate additionally requires
  a genuinely *rare* shared name token — two identical **common** names must not
  clear (C4).

Converging the two policies would either weaken coref's C4 guarantee or change
facility-crosswalk scores — if ever done, it is a benchmarked scoring change,
not a refactor. What lives here is the shared vocabulary: the floor constant
and the token-distinctiveness primitives.
"""

from __future__ import annotations

import contextlib

from typing import TYPE_CHECKING

from arche.resolve._tokenfreq import DEFAULT_TOKEN_RULE, _tokens

if TYPE_CHECKING:
    from arche.resolve._tokenfreq import TokenFrequencyTable

# The floor a distinctive signal must clear to permit a match/merge. One
# constant, used by both engines and surfaced in coref's pins.
DISTINCTIVE_FLOOR = 0.75

def name_tokens(text: str, rule: str = DEFAULT_TOKEN_RULE) -> set[str]:
    """Normalised alphanumeric name tokens, under a table's tokenisation rule.

    This used to keep its own ``_TOKEN_RE``, duplicating the one in
    :mod:`arche.resolve._tokenfreq`, with a docstring asserting the two
    "match". Nothing enforced that. Changing one and not the other produced no
    error and no warning — the table counted one vocabulary while the gate
    looked up another, so a rule could appear simply not to work. The tokeniser
    now lives in exactly one place and the *rule* travels on the table.
    """
    return set(_tokens(text, rule))


def ordered_name_tokens(text: str, rule: str = DEFAULT_TOKEN_RULE) -> list[str]:
    """The same tokens, in the order they appear.

    Orthographic keying needs order: joining *adjacent* tokens is what lets
    ``"Mai Tsidau"`` meet ``"Maitsidau"``, and adjacency is meaningless once
    the tokens are in a set.
    """
    return _tokens(text, rule)


def distinctive_residual(
    name_a: str,
    name_b: str,
    tf: TokenFrequencyTable,
    *,
    floor: float = DISTINCTIVE_FLOOR,
) -> float:
    """Rarity of what is left on each side once generic words are removed.

    :func:`shared_name_distinctiveness` requires a *literally* shared token, so
    a one-letter spelling difference in the part that actually identifies the
    place ("Kalahaddi Health Post" vs "Kalahadi Health Post") falls back to the
    rarity of ``health`` and ``post`` and reads as generic — demoting a true
    match measured at the same coordinates.

    This asks the other question: strip the tokens the corpus says are common
    and see whether each side still has a rare word in it. The frequency table
    does the stripping, so no facility-type vocabulary is needed and the answer
    is a property of the population rather than of a curated list.

    Returns the weaker side's best remaining token, so both records must carry
    something distinctive. Zero when either side is generic throughout — which
    is exactly the "General Hospital" case this is meant to catch.

    This is only ever combined with ``max`` against the literal measure, so it
    can recover pairs that were being demoted and can never lower a score.
    """
    rule = getattr(tf, "token_rule", DEFAULT_TOKEN_RULE)
    best_side: list[float] = []
    for name in (name_a, name_b):
        rare = [tf.distinctiveness(t) for t in name_tokens(name, rule)
                if tf.distinctiveness(t) >= floor]
        if not rare:
            return 0.0
        best_side.append(max(rare))
    return min(best_side)


def shared_name_distinctiveness(
    name_a: str,
    name_b: str,
    tf: TokenFrequencyTable,
    *,
    orthography: str | None = None,
) -> float:
    """Distinctiveness of the rarest shared name token, or 0.0.

    The max distinctiveness among tokens the two names literally share. Zero
    when they share no token (the transliteration case — cultural equivalence
    may lift the name *similarity*, but no distinctive token is actually in
    common, so a gate must not clear on it).

    ``orthography`` optionally names a pack (e.g. ``"hausa"``) describing how
    one name gets written two ways in the same registry system. Tokens are then
    compared through an orthographic key, so ``"Mai Tsidau"`` and
    ``"Maitsidau"`` are seen to share a word. This is **additive**: the score
    is the max over literal and keyed overlap, so enabling a pack can only
    recover pairs that were being dropped, never lower an existing score or
    move the floor. Off by default.
    """
    # The rule comes from the TABLE, never from the call site: a table counted
    # under one tokenisation and queried under another looks up tokens whose
    # counts mean something else.
    rule = getattr(tf, "token_rule", DEFAULT_TOKEN_RULE)
    literal = name_tokens(name_a, rule) & name_tokens(name_b, rule)
    best = max((tf.distinctiveness(t) for t in literal), default=0.0)

    # A name can be distinctive as a PHRASE while every one of its tokens is
    # ordinary. `london`, `bridge` and `hospital` are each common; `london
    # bridge` is not. Combined with max, so this can only recover a pair that
    # was abstaining and can never demote one that already matched.
    phrase = getattr(tf, "phrase_distinctiveness", None)
    if phrase is not None:
        best = max(best, phrase(name_a, name_b))

    if orthography:
        from arche.resolve._orthography import load_orthography

        pack = load_orthography(orthography)
        if pack is not None:
            keys_a = pack.keys(ordered_name_tokens(name_a, rule))
            keys_b = pack.keys(ordered_name_tokens(name_b, rule))
            for key in keys_a.keys() & keys_b.keys():
                sources = keys_a[key] | keys_b[key]
                # Score through the SOURCE tokens, never the key itself. A
                # joined key such as "healthpost" is absent from every
                # frequency table, so scoring it directly would read as an
                # unseen — therefore rare — token and clear the gate for any
                # two facilities both ending "Health Post".
                #
                # min, not max: a compound is only as distinctive as its most
                # COMMON part. "mai"+"tsidau" is rare because "tsidau" is;
                # "health"+"post" is common because both parts are. Taking the
                # max would let one rare token drag a common compound through.
                if len(sources) > 1 and key not in sources:
                    score = min(tf.distinctiveness(s) for s in sources)
                else:
                    score = max(tf.distinctiveness(s) for s in sources)
                best = max(best, score)

    return best


def tokenset_similarity(text_a: str, text_b: str, rule: str = DEFAULT_TOKEN_RULE) -> float:
    """Overlap of two token bags, divided by the smaller one.

    Built for long, differently-ordered, differently-detailed text — a retail
    product title, a catalogue description, a facility name with a trailing
    address. The `name` comparators are sequence measures tuned for two to four
    tokens of personal or place name, and on a fifteen-token title they punish
    exactly the two things that vary hardest between two systems describing one
    thing: **word order and level of detail**.

    Measured on 400 cross-retailer offer pairs against hard negatives (same
    brand, different product), each measure used alone at its own best
    threshold::

        containment    thr 0.40   P 0.830   R 0.890   F1 0.859
        `name`         thr 0.62   P 0.593   R 0.895   F1 0.713

    The separation is the reason, not the headline. `name` puts true pairs at
    p10 0.617 and negatives at p90 0.840 — the distributions overlap, so no
    threshold divides them and the gate has to be set high enough to lose most
    true pairs. Containment puts true pairs at p10 0.381 against negatives at
    p90 0.462, which a threshold can actually separate.

    **Divided by the smaller bag, not the union.** Jaccard punishes a verbose
    listing for being verbose: one retailer writes `Wool Area Rug` and the other
    writes `Handmade Traditional Oriental Premium Wool Area Rug`, and the
    shorter one is not a weaker claim about the same rug. Containment asks "is
    everything the terser side says also said by the other", which is the
    question two catalogues are actually being compared on.

    That asymmetry is also its weakness, and it is why this must not be the only
    signal: a two-token title is contained in almost anything. Pair it with the
    refuting comparators — a bag fully contained in another can still be a
    different variant, which is what `spec` and `rival` are for.
    """
    tokens_a, tokens_b = name_tokens(text_a, rule), name_tokens(text_b, rule)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


#: A token appearing at least this often per word of general English is an
#: ordinary word rather than a label. 1e-5 is one in a hundred thousand.
#:
#: Measured against the tokens that made `rival` misfire and the ones it exists
#: to catch, on the shipped 6.7M-token table::
#:
#:     ordinary, disqualified   reach 580 · knight 186 · wool 98 · spout 82
#:     label-like, qualified    bethanie 0 · at21e 0 · eudes 0 · cherry 37
#:
#: A rate rather than a count, so rebuilding the table at a different size does
#: not silently move the boundary.
_ORDINARY_WORD_RATE = 1e-5


def _is_ordinary_english(token: str) -> bool:
    """Is this token a word, rather than a label?

    `rival` needs to know which unshared tokens *identify* something. Rarity in
    a self-calibrated catalogue table cannot tell it: `spout` appears twice in
    1,200 product titles, which makes it rare in that catalogue and says nothing
    about whether it names a product. Refuting on it cost 26 true pairs out of
    150 in the benchmark -- the largest recoverable bucket there.

    General English answers it directly. `spout` and `reach` are words;
    `bethanie` and `at21e` are not English at all.

    **Returns False when the table is unavailable**, so a checkout that has not
    built the asset behaves exactly as it did before this existed rather than
    refusing to run. A missing table must not silently change verdicts in the
    other direction either -- False means "not known to be ordinary", which
    leaves the pre-existing rarity test as the only filter.
    """
    counts = _english_counts()
    if not counts:
        return False
    # Raw counts, NOT `rel_freq`. An unseen token gets the table's
    # `unknown_floor` (5e-5) from `rel_freq`, which is *above* this threshold --
    # so every label the filter exists to keep came back "ordinary" and the
    # filter silently disabled the rule. The floor is the right answer for a
    # rarity question and the wrong one for a membership question, and this is
    # a membership question: is the token in the dictionary at all.
    seen, total = counts
    return seen.get(token, 0) / total >= _ORDINARY_WORD_RATE


_ENGLISH: list = []


def _english_counts():
    """`(counts, total)` for the shipped English table, or None if absent."""
    if _ENGLISH:
        return _ENGLISH[0]
    loaded = None
    try:
        from arche.resolve._tokenfreq import TokenFrequencyTable as _Table

        table = _Table.default("english")
        counts = table._as_counts()  # noqa: SLF001
        total = sum(counts.values())
        if counts and total:
            loaded = (counts, total)
    except (ImportError, ValueError, FileNotFoundError, OSError, AttributeError):
        loaded = None
    _ENGLISH.append(loaded)
    return loaded


def rival_distinctive_tokens(
    name_a: str,
    name_b: str,
    tf: TokenFrequencyTable,
    *,
    floor: float = DISTINCTIVE_FLOOR,
) -> float | None:
    """Do both names carry a distinctive token the other lacks?

    Returns ``0.0`` when they do — evidence of two different things — and
    ``None`` otherwise, so it can only ever refute and never manufactures
    agreement. Pair it with ``refutes_below`` and weight 0.0.

    **The mutual requirement is the whole safety property.** One side carrying a
    rare token the other lacks means almost nothing: retailers write titles at
    different lengths, and the terser listing of a true pair is missing tokens
    constantly. Two sides *each* carrying their own rare token is different.
    Both are trying to identify something, and they are identifying different
    things::

        A: SAFAVIEH Antiquity Collection ... Oval Blue AT21E ... Wool Area Rug
        B: SAFAVIEH Antiquity Bethanie Traditional Wool Area Rug, Blue/Beige, ...

    Same collection, size, shape, colour and material. `at21e` is a product
    code, `bethanie` is a design name, neither appears on the other side, and
    they are two different rugs. Measured on 600 cross-retailer offer pairs,
    that one shape was 41 of 43 false merges.

    ``floor`` is the same ``DISTINCTIVE_FLOOR`` the match gate uses, and
    deliberately so: a token rare enough to carry a match on its own is rare
    enough that its absence on the other side means something. Nothing here
    invents a second notion of rare.

    Not a word list, and no category to maintain — which is why it lives beside
    the gate rather than in a product category. It settles ``Eudes`` against
    ``Cherry Blossom`` on the same reasoning.

    Two ways it deliberately stays quiet:

    * **A missing side.** If either name contributes no distinctive unshared
      token, this is not comparable. A terse listing is not a contradiction.
    * **A shared distinctive token.** Handled by the caller's other
      comparators; this one is about what is *not* shared.
    """
    rule = getattr(tf, "token_rule", DEFAULT_TOKEN_RULE)
    tokens_a, tokens_b = name_tokens(name_a, rule), name_tokens(name_b, rule)
    only_a, only_b = tokens_a - tokens_b, tokens_b - tokens_a
    if not only_a or not only_b:
        return None

    # Spelling variants are not rival identifiers. `panels` against `panel` and
    # `showerscape` against `scape` are one word written two ways, and both were
    # scoring as two distinctive tokens neither side shared -- refuting true
    # pairs that agreed on everything. Drop any token that contains, or is
    # contained by, a token on the other side.
    only_a = {t for t in only_a if not any(t in u or u in t for u in only_b)}
    only_b = {t for t in only_b if not any(t in u or u in t for u in tokens_a)}
    if not only_a or not only_b:
        return None

    threshold = floor * _distinctiveness_ceiling(tf)

    # A shared distinctive token outranks unshared ones, and this is the
    # difference between the two shapes that otherwise look identical:
    #
    #   Kingston Brass KB241KL Tub and Shower Faucet ... 5-Inch Spout Reach
    #   Kingston Brass KB241KL Knight Tub and Shower Faucet
    #
    # One catalogue names the model, the other describes the part. They share
    # `kb241kl`, which identifies the product outright, and `spout` against
    # `knight` is two descriptions of one thing. Contrast the rug pair, which
    # shares only `safavieh`, `antiquity`, `oval`, `wool` -- ordinary in this
    # corpus -- so nothing positively identifies either side.
    #
    # Without this the rule refuted 45 true pairs to remove 23 false ones.
    if shared_name_distinctiveness(name_a, name_b, tf) >= threshold:
        return None

    # An ordinary English word is not an identifier, however rare it happens to
    # be in this particular catalogue. Without this the rule refuted on `spout`
    # against `knight` -- one listing describing the part, the other naming the
    # model -- because a 1,200-title corpus had seen `spout` twice.
    only_a = {t for t in only_a if not _is_ordinary_english(t)}
    only_b = {t for t in only_b if not _is_ordinary_english(t)}
    if not only_a or not only_b:
        return None

    best_a = max((tf.distinctiveness(t) for t in only_a), default=0.0)
    best_b = max((tf.distinctiveness(t) for t in only_b), default=0.0)
    if best_a >= threshold and best_b >= threshold:
        return 0.0
    return None


def _distinctiveness_ceiling(tf: TokenFrequencyTable) -> float:
    """The highest distinctiveness this table can actually produce.

    ``distinctiveness`` is ``-log10(rel_freq) / 5``, calibrated for the
    million-token corpora the shipped place and person tables are built from. A
    self-calibrated table over two catalogues is far smaller, so its scale is
    compressed and the constant floor becomes unreachable. Measured on 600
    cross-retailer offer pairs: the rarest token in that corpus scores 0.861,
    and the two product identifiers this rule exists to separate score 0.721 and
    0.706 — plainly distinctive against `collection` at 0.321 and `premium` at
    0.443, and plainly under a hardcoded 0.75.

    `code_rarity` hit this exact wall and solved it the same way, in its own
    words: relative to what unique looks like in THIS corpus, not to a constant
    that a particular catalogue size happens to produce. Scoring against the
    constant demoted every true product match there and cost recall 0.2197 ->
    0.0948.

    Cached on the table because the answer is a property of the table, and a
    linear scan per candidate pair over thousands of pairs is real time spent
    recomputing a constant.
    """
    cached = getattr(tf, "_rival_ceiling", None)
    if cached is not None:
        return cached
    try:
        counts = tf._as_counts()
    except Exception:  # noqa: BLE001 - a table that cannot enumerate is not fatal
        counts = None
    ceiling = 1.0
    if counts:
        rarest = min(counts, key=counts.__getitem__)
        # Never let a degenerate table make the threshold zero, which would
        # refute every pair carrying any unshared token at all.
        ceiling = max(tf.distinctiveness(rarest), 0.2)
    with contextlib.suppress(AttributeError, TypeError):
        tf._rival_ceiling = ceiling
    return ceiling


__all__ = ["DISTINCTIVE_FLOOR", "name_tokens", "rival_distinctive_tokens",
           "tokenset_similarity",
           "shared_name_distinctiveness"]
