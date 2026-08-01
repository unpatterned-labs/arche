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


def shared_name_distinctiveness(
    name_a: str, name_b: str, tf: TokenFrequencyTable
) -> float:
    """Distinctiveness of the rarest shared name token, or 0.0.

    The max distinctiveness among tokens the two names literally share. Zero
    when they share no token (the transliteration case — cultural equivalence
    may lift the name *similarity*, but no distinctive token is actually in
    common, so a gate must not clear on it).
    """
    shared = name_tokens(name_a) & name_tokens(name_b)
    if not shared:
        return 0.0
    return max(tf.distinctiveness(t) for t in shared)


__all__ = ["DISTINCTIVE_FLOOR", "name_tokens", "shared_name_distinctiveness"]
