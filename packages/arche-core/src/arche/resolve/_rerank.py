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

"""Block-aware distinguishing-token reranker (the uk_address_matcher idea).

A pairwise score treats every token equally. But *within a block of candidates*
some tokens carry the whole decision. Reconciling "10 Downing Street" against a
block of {"10 Downing Street", "11 Downing Street"}, the house number is the
only thing that distinguishes them — the street/city/postcode are shared by
every candidate and decide nothing.

This reranker adjusts a base score using the block context:

* **Reward** tokens the pair shares, weighted by their corpus distinctiveness —
  agreeing on a rare token is real evidence of the same place.
* **Punish** a token that ``a`` has and ``b`` lacks *but another candidate in
  a's block has* — that token discriminates within the block, and ``b`` is on
  the wrong side of it. A token every candidate shares (or none do) is not
  discriminating and never punishes.

Reimplemented clean from the concept — no dependency on uk_address_matcher.
~40 lines of Counter/set arithmetic.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from arche.resolve._tokenfreq import TokenFrequencyTable, _tokens


def rerank_score(
    base: float,
    a_text: str,
    b_text: str,
    other_texts: Iterable[str],
    tf: TokenFrequencyTable,
    *,
    reward: float = 0.20,
    punish: float = 0.20,
) -> float:
    """Adjust ``base`` for pair (a, b) given the other candidates in a's block.

    ``other_texts`` are the rerank-texts of the *other* b-candidates blocked
    with ``a`` (excluding ``b`` itself). ``tf`` supplies token distinctiveness.
    Returns a score clamped to ``[0, 1]``. With an empty block context and no
    shared tokens the score is unchanged.
    """
    a_toks = set(_tokens(a_text))
    b_toks = set(_tokens(b_text))
    if not a_toks or not b_toks:
        return max(0.0, min(1.0, base))

    # How often each token shows up across the OTHER candidates of a's block.
    block: Counter[str] = Counter()
    for txt in other_texts:
        block.update(set(_tokens(txt)))

    # Reward: shared tokens, weighted by how distinctive each is in the corpus.
    # Distinctiveness is in [0, 1], so a shared *rare* token (near 1) rewards
    # far more than a shared *common* one (near 0) — the signal must survive
    # into the adjustment, so we do NOT normalise it away.
    shared = a_toks & b_toks
    reward_amt = sum(tf.distinctiveness(t) for t in shared)

    # Punish: a-tokens b lacks that DO appear in another candidate -> they
    # discriminate within the block, and b is on the losing side.
    punish_amt = sum(
        tf.distinctiveness(t)
        for t in a_toks
        if t not in b_toks and block.get(t, 0) > 0
    )

    # The coefficients keep each token's contribution a small nudge; the clamp
    # bounds the cumulative effect. No normalisation — that would cancel the
    # distinctiveness weighting we just computed.
    adjusted = base + reward * reward_amt - punish * punish_amt
    return max(0.0, min(1.0, adjusted))
