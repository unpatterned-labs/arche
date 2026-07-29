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

"""Corpus term-frequency token weighting — distinctiveness for record linkage.

Agreement on a *rare* token (a distinctive town / facility / person name) is
strong evidence two records are the same thing; agreement on a *common* token
("Central", "General", "Lagos", "PHC") is nearly none. This generalizes the
matcher's static per-jurisdiction ``common_name_u`` dict into a table COMPUTED
over the list being resolved — the term-frequency adjustment a Splink user gets
from their own data, precomputed here.

"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from arche.resolve._matcher import _normalise_text

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Relative-frequency floor for a token never seen in the corpus. A brand-new
# token is treated as rare-but-not-impossible (uk_address_matcher uses 5e-5).
_UNKNOWN_FLOOR = 5e-5


def _tokens(text: str) -> list[str]:
    """Normalised alphanumeric tokens (lowercased, diacritics stripped)."""
    return _TOKEN_RE.findall(_normalise_text(text or ""))


class TokenFrequencyTable:
    """Relative token frequencies over a corpus, with a distinctiveness weight.

    Build once over the list(s) being reconciled, then reuse for every pair::

        tf = TokenFrequencyTable.from_corpus(name for r in records)
        tf.weighted_token_sim("Karfi PHC", "Karfi Clinic")   # rare overlap -> high
        tf.weighted_token_sim("Central PHC", "Central Clinic")  # common overlap -> low
    """

    def __init__(self, rel_freq: dict[str, float], *,
                 unknown_floor: float = _UNKNOWN_FLOOR) -> None:
        self._rel = rel_freq
        self._floor = unknown_floor

    @classmethod
    def from_corpus(cls, texts: Iterable[str], *,
                    unknown_floor: float = _UNKNOWN_FLOOR) -> TokenFrequencyTable:
        counts: Counter[str] = Counter()
        for t in texts:
            counts.update(_tokens(t))
        total = sum(counts.values()) or 1
        rel = {tok: c / total for tok, c in counts.items()}
        return cls(rel, unknown_floor=unknown_floor)

    def rel_freq(self, token: str) -> float:
        """Relative frequency of ``token`` in the corpus (floored if unseen)."""
        return self._rel.get(_normalise_text(token), self._floor)

    def distinctiveness(self, token: str) -> float:
        """How distinctive a token is: 0 (ubiquitous) .. 1 (unique / unseen).

        ``-log10(rel_freq)`` normalised over a 5-decade span, so ``rel_freq``
        1e-5 or rarer scores ~1.0 and a token that is ~all of the corpus scores
        ~0.0.
        """
        f = max(self.rel_freq(token), 1e-12)
        return min(1.0, max(0.0, -math.log10(f) / 5.0))

    def u_for(self, token: str) -> float:
        """Fellegi-Sunter u proxy: P(agree | non-match) ≈ rel_freq.

        Frequent token -> high u -> weak evidence; rare token -> tiny u -> strong
        evidence. Shaped like the matcher's ``common_name_u`` values so it can be
        injected into ``JurisdictionPriors.common_name_u``.
        """
        return max(self.rel_freq(token), self._floor)

    def common_u_map(self, min_freq: float = 1e-4) -> dict[str, float]:
        """{token: u} for the COMMON tokens (rel_freq >= ``min_freq``).

        For injecting into ``JurisdictionPriors.common_name_u`` so ``compare_names``
        down-weights agreement on frequent names in this population.
        """
        return {tok: f for tok, f in self._rel.items() if f >= min_freq}

    def weighted_token_sim(self, a: str, b: str) -> float:
        """TF-weighted token-set similarity in [0, 1] (distinctiveness-weighted Jaccard).

        Overlap is weighted by distinctiveness, so agreeing on a rare token counts
        far more than agreeing on a common one. Returns 0.0 if either side has no
        tokens.
        """
        ta, tb = set(_tokens(a)), set(_tokens(b))
        if not ta or not tb:
            return 0.0
        inter, union = ta & tb, ta | tb
        num = sum(self.distinctiveness(t) for t in inter)
        den = sum(self.distinctiveness(t) for t in union)
        return num / den if den else 0.0
