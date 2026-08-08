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

import re
from typing import TYPE_CHECKING

from arche.resolve._matcher import _normalise_text

if TYPE_CHECKING:
    from arche.resolve._tokenfreq import TokenFrequencyTable

# The floor a distinctive signal must clear to permit a match/merge. One
# constant, used by both engines and surfaced in coref's pins.
DISTINCTIVE_FLOOR = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def name_tokens(text: str) -> set[str]:
    """Normalised alphanumeric name tokens (matching the TF tokenizer)."""
    return set(_TOKEN_RE.findall(_normalise_text(text or "")))


def ordered_name_tokens(text: str) -> list[str]:
    """The same tokens, in the order they appear.

    Orthographic keying needs order: joining *adjacent* tokens is what lets
    ``"Mai Tsidau"`` meet ``"Maitsidau"``, and adjacency is meaningless once
    the tokens are in a set.
    """
    return _TOKEN_RE.findall(_normalise_text(text or ""))


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
    literal = name_tokens(name_a) & name_tokens(name_b)
    best = max((tf.distinctiveness(t) for t in literal), default=0.0)

    if orthography:
        from arche.resolve._orthography import load_orthography

        pack = load_orthography(orthography)
        if pack is not None:
            keys_a = pack.keys(ordered_name_tokens(name_a))
            keys_b = pack.keys(ordered_name_tokens(name_b))
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
