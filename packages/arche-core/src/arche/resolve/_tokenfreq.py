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
# The English possessive as it survives `_normalise_text`, which lowercases and
# strips diacritics but leaves apostrophes alone.
_POSSESSIVE_RE = re.compile(r"([a-z0-9]+)['’]s(?![a-z0-9])")

#: How a name becomes tokens. The rule is a property of a *table*, not of a
#: call site: a table counted under one rule and queried under another silently
#: undercounts, because the query looks up a token whose count was accumulated
#: differently. :class:`TokenFrequencyTable` therefore carries its own rule and
#: every consumer asks the table rather than tokenising on its own account.
#:
#: ``plain``       the historical rule. ``Queen's`` -> ``queen``, ``s``.
#: ``possessive``  emits the joined form ALONGSIDE, never instead:
#:                 ``Queen's`` -> ``queen``, ``s``, ``queens``. Additive by
#:                 set-union, so the shared-token set is a superset of
#:                 ``plain``'s and a gate can only ever see more evidence.
#:                 Folding (emitting ``queens`` *instead*) was measured and
#:                 rejected: it demotes ``St Mary Hospital`` against
#:                 ``St Mary's Hospital`` from 0.683 to 0.504.
TOKEN_RULES = ("plain", "possessive")
DEFAULT_TOKEN_RULE = "plain"
# Relative-frequency floor for a token never seen in the corpus. A brand-new
# token is treated as rare-but-not-impossible (uk_address_matcher uses 5e-5).
_UNKNOWN_FLOOR = 5e-5
# Serialization tag + the frequency tables shipped in the wheel, one per
# entity domain (each with the builder script that regenerates it).
_FORMAT = "arche-tf/1"
_DEFAULT_RESOURCES = {
    "person": "name_frequencies.json.gz",
    "artist": "artist_frequencies.json.gz",
    "place": "place_frequencies.json.gz",
}
#: Phrase (bigram) tables that accompany a unigram table. A name whose every
#: token is ordinary can still be distinctive as a PHRASE: `london`, `bridge`
#: and `hospital` are all common, `london bridge` is not. Only `place` has one.
_DEFAULT_PHRASES = {
    "place": "place_bigrams.json.gz",
}
_DEFAULT_BUILDERS = {
    "person": "datasets/names_dataops/build_name_frequencies.py",
    "artist": "datasets/artists_dataops/build_artist_frequencies.py",
    "place": "datasets/places_dataops/build_place_frequencies.py",
}
# Process-wide cache for the packaged default tables (they are immutable).
_DEFAULT_CACHE: dict[str, TokenFrequencyTable] = {}


def _tokens(text: str, rule: str = DEFAULT_TOKEN_RULE) -> list[str]:
    """Normalised alphanumeric tokens (lowercased, diacritics stripped).

    ``rule`` selects an emission from :data:`TOKEN_RULES`. Pass the rule the
    *table* was built with — see :attr:`TokenFrequencyTable.token_rule` — never
    a rule chosen at the call site.
    """
    if rule not in TOKEN_RULES:
        raise ValueError(f"unknown token rule {rule!r}; expected one of {list(TOKEN_RULES)}")
    norm = _normalise_text(text or "")
    out = _TOKEN_RE.findall(norm)
    if rule == "possessive":
        # Alongside, never instead. See TOKEN_RULES.
        out.extend(m.group(1) + "s" for m in _POSSESSIVE_RE.finditer(norm))
    return out


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
        population_scale: bool = False,
        token_rule: str = DEFAULT_TOKEN_RULE,
    ) -> None:
        """Construct from either raw ``counts`` (preferred — retains totals for
        :meth:`merge` / :meth:`most_common`) or a precomputed ``rel_freq`` map
        (legacy; no raw counts). Keys are normalised on the way in.
        """
        self._floor = unknown_floor
        # Whether this table can support a RARITY claim. `distinctiveness` is
        # -log10(rel_freq)/5, which is calibrated against population
        # frequencies. Over a 2,000-name corpus the rarest possible token sits
        # near 0.77 and a token seen twice near 0.71, so a 0.75 gate would
        # refuse everything — thresholds are not a property of the measure
        # alone, they depend on corpus size (Draisbach & Naumann, ICIQ 2013).
        # A gate may only consult distinctiveness when this is True.
        self.population_scale = bool(population_scale)
        # Content version of a shipped table, or None for one built at runtime.
        # Carried into `pins` so a decision names the exact frequency data that
        # produced it — the same discipline as the declaration pin.
        self.version: str | None = None
        #: The tokenisation this table's counts were accumulated under. Every
        #: consumer must tokenise the same way or the lookup lands on a token
        #: whose count means something else.
        if token_rule not in TOKEN_RULES:
            raise ValueError(
                f"unknown token rule {token_rule!r}; expected one of {list(TOKEN_RULES)}"
            )
        self.token_rule: str = token_rule
        #: Optional companion table of phrase (bigram) frequencies, built over
        #: the same corpus under the same rule. `None` when the domain has no
        #: phrase table or one was not found.
        self.phrases: TokenFrequencyTable | None = None
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
        cls, texts: Iterable[str], *, unknown_floor: float = _UNKNOWN_FLOOR,
        token_rule: str = DEFAULT_TOKEN_RULE,
    ) -> TokenFrequencyTable:
        """Count tokens over ``texts`` (self-calibrating over the list resolved)."""
        counts: Counter[str] = Counter()
        for t in texts:
            counts.update(_tokens(t, token_rule))
        return cls(counts=counts, unknown_floor=unknown_floor, token_rule=token_rule)

    @classmethod
    def from_counts(
        cls, counts: Mapping[str, float], *, unknown_floor: float = _UNKNOWN_FLOOR,
        token_rule: str = DEFAULT_TOKEN_RULE,
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
            for tok in _tokens(name, token_rule):
                agg[tok] += float(c)
        return cls(counts=agg, unknown_floor=unknown_floor, population_scale=True,
                   token_rule=token_rule)

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
                    table = cls.load(path)
                    phrase_name = _DEFAULT_PHRASES.get(domain)
                    if phrase_name is not None:
                        phrase_path = path.parent / phrase_name
                        if phrase_path.exists():
                            phrases = cls.load(phrase_path)
                            if phrases.token_rule != table.token_rule:
                                raise ValueError(
                                    f"phrase table {phrase_name} was built under "
                                    f"{phrases.token_rule!r} but its unigram table "
                                    f"under {table.token_rule!r}; a phrase assembled "
                                    f"from one tokenisation cannot be looked up in "
                                    f"counts accumulated under another"
                                )
                            table.phrases = phrases
                    _DEFAULT_CACHE[domain] = table
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
        # This is a RATIO, so a rule that emits extra tokens is not
        # automatically safe: when only one side carries a possessive, the
        # extra token inflates the union and the score falls. Measured on
        # "St Mary Hospital" vs "St Mary's Hospital": 0.763 -> 0.563 under the
        # possessive rule alone. So score under the table's rule AND under
        # `plain`, and take the better — strictly additive, so a richer
        # tokenisation can only ever recover a pair, never demote one.
        if self.token_rule != DEFAULT_TOKEN_RULE:
            best = self._token_sim(a, b, DEFAULT_TOKEN_RULE, orthography)
            return max(best, self._token_sim(a, b, self.token_rule, orthography))
        return self._token_sim(a, b, self.token_rule, orthography)

    def _token_sim(self, a: str, b: str, rule: str, orthography: str | None) -> float:
        """One tokenisation's distinctiveness-weighted Jaccard."""
        ta, tb = set(_tokens(a, rule)), set(_tokens(b, rule))
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
                keys_a = pack.keys(_tokens(a, rule))
                keys_b = pack.keys(_tokens(b, rule))

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

    def phrase_distinctiveness(self, a: str, b: str) -> float:
        """Rarity of the rarest shared phrase, or 0.0 when none is shared.

        The gate asks whether two names share something *rare* and asks it of
        tokens. That is right where the identifying part of a name is one rare
        word — ``Karfi Health Post`` clears on ``karfi``. It is wrong where
        identity lives in a phrase of ordinary words: every token of
        ``London Bridge Hospital`` is common, so two records of that hospital
        30 m apart with byte-identical names abstained.

        The corpus separates the two cases with no curation at all::

            general hospital 0.486    london bridge 0.921
            health post      0.349    kings college 0.967

        Returns 0.0 — never a default rarity — when there is no phrase table,
        when it is not population-scale, or when the two names share no phrase.
        A caller combines this with the token measure using ``max``, so it can
        only ever recover a pair.
        """
        phrases = self.phrases
        if phrases is None or not phrases.population_scale:
            return 0.0
        rule = phrases.token_rule
        ta, tb = _tokens(a, rule), _tokens(b, rule)
        ga = {" ".join(ta[i:i + 2]) for i in range(len(ta) - 1)}
        gb = {" ".join(tb[i:i + 2]) for i in range(len(tb) - 1)}
        shared = ga & gb
        if not shared:
            return 0.0
        # Only phrases the corpus has actually SEEN may speak. An unseen phrase
        # would score at the unknown floor and read as maximally distinctive —
        # the `healthpost` failure, at phrase scale where counts are sparser.
        #
        # Test membership in the counts, NOT `rel_freq(g) > floor`: `rel_freq`
        # clamps at the floor, so a genuinely rare phrase and an unseen one
        # return the same number. `london bridge` sits below the floor and is
        # real; that check silently discarded it.
        counts = phrases._counts or {}
        seen = [g for g in shared if g in counts]
        return max((phrases.distinctiveness(g) for g in seen), default=0.0)

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
        if self.token_rule != other.token_rule:
            raise ValueError(
                f"cannot merge tables built under different tokenisations: "
                f"{self.token_rule!r} and {other.token_rule!r}. Counts accumulated "
                f"under one rule do not mean the same thing under another."
            )
        merged: Counter[str] = Counter()
        for tok, c in self._as_counts().items():
            merged[tok] += c * weight
        for tok, c in other._as_counts().items():
            merged[tok] += c * other_weight
        return TokenFrequencyTable(
            counts=merged,
            unknown_floor=min(self._floor, other._floor),
            # Merging a population table with a local corpus keeps the
            # population claim: the result is still calibrated against a
            # population, just with local counts folded in.
            population_scale=self.population_scale or other.population_scale,
            token_rule=self.token_rule,
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
        d: dict = {"format": _FORMAT, "unknown_floor": self._floor,
                   "token_rule": self.token_rule}
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
        # A serialised table is a published artefact, not a scratch count over
        # the two lists in hand, so it may support a rarity claim.
        # A table built before token rules existed is `plain` by definition.
        rule = d.get("token_rule", DEFAULT_TOKEN_RULE)
        if "counts" in d:
            tbl = cls(counts=d["counts"], total=d.get("total"),
                      unknown_floor=floor, population_scale=True, token_rule=rule)
        else:
            tbl = cls(d.get("rel_freq", {}), unknown_floor=floor,
                      population_scale=True, token_rule=rule)
        tbl.version = d.get("version")
        return tbl

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
