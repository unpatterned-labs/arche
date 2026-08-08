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
over a corpus — the term-frequency adjustment a Splink user gets from their own
data, precomputed here.

Two ways to build a table:

* :meth:`TokenFrequencyTable.from_corpus` counts tokens over the list(s) being
  resolved (the local, self-calibrating path).
* :meth:`TokenFrequencyTable.from_counts` ingests a *precomputed* frequency list
  — a national name-frequency table (US Census surnames, a ParaNames-derived
  African token table, …). This is the moat: population-scale distinctiveness
  that a single small list can't estimate. Built tables :meth:`save` / :meth:`load`
  as gzipped JSON and :meth:`merge` across sources.

:meth:`TokenFrequencyTable.default` loads the frequency table shipped in the
wheel so distinctiveness weighting works out of the box.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from arche.resolve._matcher import _normalise_text

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Relative-frequency floor for a token never seen in the corpus. A brand-new
# token is treated as rare-but-not-impossible (uk_address_matcher uses 5e-5).
_UNKNOWN_FLOOR = 5e-5
# Serialization tag + the frequency tables shipped in the wheel, one per
# entity domain (each with the builder script that regenerates it).
_FORMAT = "arche-tf/1"
_DEFAULT_RESOURCES = {
    "person": "name_frequencies.json.gz",
    "artist": "artist_frequencies.json.gz",
}
_DEFAULT_BUILDERS = {
    "person": "datasets/names_dataops/build_name_frequencies.py",
    "artist": "datasets/artists_dataops/build_artist_frequencies.py",
}
# Process-wide cache for the packaged default tables (they are immutable).
_DEFAULT_CACHE: dict[str, TokenFrequencyTable] = {}


def _tokens(text: str) -> list[str]:
    """Normalised alphanumeric tokens (lowercased, diacritics stripped)."""
    return _TOKEN_RE.findall(_normalise_text(text or ""))


class TokenFrequencyTable:
    """Relative token frequencies over a corpus, with a distinctiveness weight.

    Build once, then reuse for every pair::

        tf = TokenFrequencyTable.from_corpus(name for r in records)
        tf.weighted_token_sim("Karfi PHC", "Karfi Clinic")      # rare overlap -> high
        tf.weighted_token_sim("Central PHC", "Central Clinic")  # common overlap -> low

    or load the population-scale table shipped with arche::

        tf = TokenFrequencyTable.default()
    """

    def __init__(
        self,
        rel_freq: Mapping[str, float] | None = None,
        *,
        counts: Mapping[str, float] | None = None,
        total: float | None = None,
        unknown_floor: float = _UNKNOWN_FLOOR,
    ) -> None:
        """Construct from either raw ``counts`` (preferred — retains totals for
        :meth:`merge` / :meth:`most_common`) or a precomputed ``rel_freq`` map
        (legacy; no raw counts). Keys are normalised on the way in.
        """
        self._floor = unknown_floor
        if counts is not None:
            norm: Counter[str] = Counter()
            for tok, c in counts.items():
                norm[_normalise_text(tok)] += float(c)
            self._counts: dict[str, float] | None = dict(norm)
            self._total: float = float(total) if total is not None else float(
                sum(self._counts.values())
            )
            if self._total <= 0:
                self._total = 1.0
            self._rel: dict[str, float] = {
                tok: c / self._total for tok, c in self._counts.items()
            }
        elif rel_freq is not None:
            self._rel = {_normalise_text(t): float(f) for t, f in rel_freq.items()}
            self._counts = None
            self._total = 0.0
        else:
            self._rel, self._counts, self._total = {}, {}, 0.0

    # ── builders ──────────────────────────────────────────────────────────────
    @classmethod
    def from_corpus(
        cls, texts: Iterable[str], *, unknown_floor: float = _UNKNOWN_FLOOR
    ) -> TokenFrequencyTable:
        """Count tokens over ``texts`` (self-calibrating over the list resolved)."""
        counts: Counter[str] = Counter()
        for t in texts:
            counts.update(_tokens(t))
        return cls(counts=counts, unknown_floor=unknown_floor)

    @classmethod
    def from_counts(
        cls, counts: Mapping[str, float], *, unknown_floor: float = _UNKNOWN_FLOOR
    ) -> TokenFrequencyTable:
        """Ingest a *precomputed* frequency list (``name/token -> count``).

        Each key is tokenised and its count is credited to every token it
        contains, so a national list keyed by full name (``"Fatima Abdullahi": 900``)
        and one keyed by single token (``"fatima": 900``) both aggregate
        correctly. This is how a population-scale table (Census surnames,
        ParaNames-derived African tokens) becomes distinctiveness weights.

        Keep one call to one keying convention: mixing full-name-keyed and
        single-token-keyed entries inflates the shared tokens' counts (a
        multi-token key credits its count to *each* token), skewing frequencies.
        Merge separately-built tables with :meth:`merge` instead.
        """
        agg: Counter[str] = Counter()
        for name, c in counts.items():
            for tok in _tokens(name):
                agg[tok] += float(c)
        return cls(counts=agg, unknown_floor=unknown_floor)

    @classmethod
    def default(cls, domain: str = "person") -> TokenFrequencyTable:
        """A population-scale frequency table shipped in the wheel.

        ``domain`` selects the entity population: ``"person"`` (US Census
        surnames + African names lexicon) or ``"artist"`` (MusicBrainz artist
        catalog sample). Cached process-wide. Raises :class:`ValueError` for an
        unknown domain, and :class:`FileNotFoundError` with build guidance if
        the data asset is absent (e.g. an editable checkout that has not run
        the builder).
        """
        try:
            resource_name = _DEFAULT_RESOURCES[domain]
        except KeyError:
            raise ValueError(
                f"unknown frequency-table domain {domain!r}; available: "
                f"{sorted(_DEFAULT_RESOURCES)}"
            ) from None
        if domain not in _DEFAULT_CACHE:
            from importlib.resources import as_file, files

            resource = files("arche.resolve").joinpath("_data", resource_name)
            try:
                with as_file(resource) as path:
                    _DEFAULT_CACHE[domain] = cls.load(path)
            except (FileNotFoundError, ModuleNotFoundError) as exc:
                raise FileNotFoundError(
                    f"The default {domain} frequency table is not present. "
                    f"Build it with:\n    python {_DEFAULT_BUILDERS[domain]}\n"
                    "or pass an explicit table via tf=."
                ) from exc
        return _DEFAULT_CACHE[domain]

    # ── queries (unchanged R1 surface) ─────────────────────────────────────────
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

    def weighted_token_sim(
        self, a: str, b: str, *, orthography: str | None = None
    ) -> float:
        """TF-weighted token-set similarity in [0, 1] (distinctiveness-weighted Jaccard).

        Overlap is weighted by distinctiveness, so agreeing on a rare token counts
        far more than agreeing on a common one. Returns 0.0 if either side has no
        tokens.

        ``orthography`` optionally names a pack (e.g. ``"hausa"``) describing how
        one name gets written two ways across registries. Tokens are then
        compared through an orthographic key, so ``"Mai Tsidau"`` and
        ``"Maitsidau"`` count as agreeing. Off by default: this changes scores,
        so it is a benchmarked opt-in rather than a silent default.

        Distinctiveness for a keyed group is taken from its **most common**
        member. A compound is only as rare as its commonest part — otherwise a
        joined form like ``healthpost``, which appears in no frequency table,
        would read as unseen-therefore-rare and inflate every pair of
        facilities whose names both end "Health Post".
        """
        ta, tb = set(_tokens(a)), set(_tokens(b))
        if not ta or not tb:
            return 0.0

        inter, union = ta & tb, ta | tb
        num = sum(self.distinctiveness(t) for t in inter)
        den = sum(self.distinctiveness(t) for t in union)
        literal = num / den if den else 0.0

        if orthography:
            from arche.resolve._orthography import load_orthography

            pack = load_orthography(orthography)
            if pack is not None:
                keys_a = pack.keys(_tokens(a))
                keys_b = pack.keys(_tokens(b))

                def weight(key: str) -> float:
                    sources = keys_a.get(key, set()) | keys_b.get(key, set())
                    if not sources:
                        return self.distinctiveness(key)
                    return min(self.distinctiveness(s) for s in sources)

                def redundant(key: str) -> bool:
                    """A join that bridges nothing.

                    If both names already contain every component token
                    individually, the joined form carries no new agreement —
                    "Kurugu Health Post" and "Alfindi Health Post" both yield
                    ``healthpost``, but they already agreed on ``health`` and
                    ``post`` separately. Counting it again is double-counting
                    a shared type, in the direction of a false merge.
                    """
                    parts = keys_a.get(key, set()) | keys_b.get(key, set())
                    if len(parts) < 2 or key in parts:
                        return False
                    return parts <= ta and parts <= tb

                inter_k = {k for k in keys_a.keys() & keys_b.keys() if not redundant(k)}
                union_k = {k for k in keys_a.keys() | keys_b.keys() if not redundant(k)}
                num_k = sum(weight(k) for k in inter_k)
                den_k = sum(weight(k) for k in union_k)
                keyed = num_k / den_k if den_k else 0.0
                # Strictly additive. Keying restructures the Jaccard
                # denominator, which on real data cost more pairs than it
                # recovered — 13 gained against 79 lost on the Kano crosswalk.
                # Taking the max means a pack can only ever recover a pair the
                # literal comparison was dropping, never demote one it kept.
                return max(literal, keyed)

        return literal

    # ── composition + introspection ────────────────────────────────────────────
    def _as_counts(self) -> dict[str, float]:
        """Raw counts, reconstructing pseudo-counts for a legacy rel-only table."""
        if self._counts is not None:
            return self._counts
        positive = [f for f in self._rel.values() if f > 0]
        if not positive:
            return {}
        scale = 1.0 / min(positive)  # smallest positive freq -> count 1
        return {tok: f * scale for tok, f in self._rel.items() if f > 0}

    def merge(
        self,
        other: TokenFrequencyTable,
        *,
        weight: float = 1.0,
        other_weight: float = 1.0,
    ) -> TokenFrequencyTable:
        """Combine two frequency tables into a new one by summing (weighted) counts.

        ``other_weight`` lets one source dominate — e.g. trust an African name
        table over a Western surname list when resolving African records::

            table = census.merge(african, weight=1.0, other_weight=3.0)
        """
        merged: Counter[str] = Counter()
        for tok, c in self._as_counts().items():
            merged[tok] += c * weight
        for tok, c in other._as_counts().items():
            merged[tok] += c * other_weight
        return TokenFrequencyTable(
            counts=merged, unknown_floor=min(self._floor, other._floor)
        )

    def most_common(self, n: int = 20) -> list[tuple[str, float]]:
        """The ``n`` most frequent ``(token, count)`` pairs (count = rel_freq for a
        legacy rel-only table)."""
        source = self._counts if self._counts is not None else self._rel
        return sorted(source.items(), key=lambda kv: kv[1], reverse=True)[:n]

    @property
    def vocabulary_size(self) -> int:
        """Number of distinct tokens in the table."""
        return len(self._rel)

    @property
    def total_count(self) -> float:
        """Total token occurrences (0.0 for a legacy rel-only table)."""
        return self._total

    def __len__(self) -> int:
        return len(self._rel)

    def __repr__(self) -> str:
        return (
            f"TokenFrequencyTable(vocab={self.vocabulary_size}, "
            f"total={self._total:.0f})"
        )

    # ── persistence ─────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Serialise to a plain dict (counts preferred, else rel_freq)."""
        d: dict = {"format": _FORMAT, "unknown_floor": self._floor}
        if self._counts is not None:
            d["total"] = self._total
            d["counts"] = self._counts
        else:
            d["rel_freq"] = self._rel
        return d

    @classmethod
    def from_dict(cls, d: Mapping) -> TokenFrequencyTable:
        """Rebuild from :meth:`to_dict` output."""
        floor = d.get("unknown_floor", _UNKNOWN_FLOOR)
        if "counts" in d:
            return cls(counts=d["counts"], total=d.get("total"), unknown_floor=floor)
        return cls(d.get("rel_freq", {}), unknown_floor=floor)

    def save(self, path: str | Path) -> None:
        """Write to ``path`` as JSON (gzipped when the suffix is ``.gz``)."""
        path = Path(path)
        payload = json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")
        if path.suffix == ".gz":
            with gzip.open(path, "wb") as fh:
                fh.write(payload)
        else:
            path.write_bytes(payload)

    @classmethod
    def load(cls, path: str | Path) -> TokenFrequencyTable:
        """Read a table written by :meth:`save`."""
        path = Path(path)
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as fh:
                raw = fh.read()
        else:
            raw = Path(path).read_bytes()
        return cls.from_dict(json.loads(raw))
