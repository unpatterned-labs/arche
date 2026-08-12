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


__all__ = ["DISTINCTIVE_FLOOR", "name_tokens", "shared_name_distinctiveness"]
