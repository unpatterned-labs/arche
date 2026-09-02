# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tokenisation rules, and the agreement they are supposed to guarantee.

`_gate` used to keep its own `_TOKEN_RE`, duplicating the one in `_tokenfreq`,
with a docstring asserting the two "match". Nothing enforced it. Editing one and
not the other produced no error and no warning: the frequency table counted one
vocabulary while the gate looked up another, so a new tokenisation rule appeared
simply not to work while every test stayed green.

These tests exist so that cannot recur. They assert three separate things:

1. there is exactly one tokeniser, and the gate delegates to it;
2. a rule is a property of a *table*, travels with it, and cannot be mixed;
3. any rule that emits extra tokens is **additive** — for the gate *and* for the
   comparator. That second half is not free: `weighted_token_sim` is a ratio, so
   a one-sided extra token inflates the union and lowers the score. Measured on
   "St Mary Hospital" vs "St Mary's Hospital", the possessive rule alone took it
   from 0.763 to 0.563 before the max-over-rules fix.
"""

from __future__ import annotations

import pytest
from arche.resolve import _gate
from arche.resolve._gate import name_tokens, shared_name_distinctiveness
from arche.resolve._tokenfreq import (
    DEFAULT_TOKEN_RULE,
    TOKEN_RULES,
    TokenFrequencyTable,
    _tokens,
)

# Representative institution names. Deliberately a fixture rather than the UK
# benchmark data: that corpus is OpenStreetMap-derived (ODbL) and is evidence,
# never a shipped asset, so tests must not depend on it.
NAMES = [
    "St George's Hospital",
    "St Mary's Hospital",
    "St Mary Hospital",
    "Queen's Hospital",
    "Queens Hospital",
    "Queen Mary's Hospital",
    "King's College Hospital",
    "Queen Charlotte's & Chelsea Hospital",
    "Queen Charlotte's and Chelsea Hospital",
    "London Bridge Hospital",
    "General Hospital",
    "Karfi Health Post",
    "Karfi Health Clinic",
    "Gyaranya Health Post",
    "Sabon Gari Clinic",
    "Ospedale Sant'Andrea",          # apostrophe that is NOT a possessive
    "Nuffield Health Highgate Hospital",
]
PAIRS = [(a, b) for i, a in enumerate(NAMES) for b in NAMES[i:]]


def _table(rule: str) -> TokenFrequencyTable:
    """A population-scale table over the fixture corpus, built under `rule`."""
    return TokenFrequencyTable.from_corpus(
        NAMES * 3, token_rule=rule,
    ).__class__(
        counts={
            t: c for t, c in
            TokenFrequencyTable.from_corpus(NAMES * 3, token_rule=rule)._as_counts().items()
        },
        population_scale=True,
        token_rule=rule,
    )


class TestSingleTokeniser:
    """One tokeniser, and the gate uses it."""

    def test_gate_no_longer_defines_its_own_token_regex(self):
        # The duplicate this whole module exists to prevent.
        assert not hasattr(_gate, "_TOKEN_RE")

    def test_gate_tokens_are_the_frequency_table_tokens(self):
        for name in NAMES:
            for rule in TOKEN_RULES:
                assert name_tokens(name, rule) == set(_tokens(name, rule))

    def test_unknown_rule_is_refused_loudly(self):
        with pytest.raises(ValueError, match="unknown token rule"):
            _tokens("St Mary's Hospital", "nonsense")
        with pytest.raises(ValueError, match="unknown token rule"):
            TokenFrequencyTable(counts={"x": 1}, token_rule="nonsense")


class TestRuleTravelsWithTheTable:
    def test_round_trips_through_serialisation(self):
        table = TokenFrequencyTable(counts={"x": 5}, token_rule="possessive")
        assert TokenFrequencyTable.from_dict(table.to_dict()).token_rule == "possessive"

    def test_legacy_payload_without_a_rule_is_plain(self):
        # Tables built before rules existed were, by definition, `plain`.
        legacy = TokenFrequencyTable.from_dict({"counts": {"y": 1}, "total": 1})
        assert legacy.token_rule == DEFAULT_TOKEN_RULE

    def test_merging_across_rules_is_refused(self):
        # Counts accumulated under one rule do not mean the same thing under
        # another; silently inheriting the left-hand rule would reintroduce
        # exactly the mismatch this module guards.
        a = TokenFrequencyTable(counts={"x": 5}, token_rule="possessive")
        b = TokenFrequencyTable(counts={"y": 1}, token_rule="plain")
        with pytest.raises(ValueError, match="different tokenisations"):
            a.merge(b)

    def test_shipped_place_table_declares_its_rule(self):
        table = TokenFrequencyTable.default(domain="place")
        assert table.token_rule in TOKEN_RULES


class TestPossessiveEmission:
    def test_emits_the_joined_form_alongside_never_instead(self):
        assert _tokens("Queen's Hospital", "possessive") == [
            "queen", "s", "hospital", "queens",
        ]

    def test_handles_both_apostrophe_characters(self):
        straight = _tokens("Queen's Hospital", "possessive")
        curly = _tokens("Queen’s Hospital", "possessive")
        assert "queens" in straight and "queens" in curly

    def test_does_not_fire_on_a_non_possessive_apostrophe(self):
        # "Sant'Andrea" is not "Sant" + possessive; there is no trailing-s
        # boundary, so nothing should be emitted.
        assert _tokens("Ospedale Sant'Andrea", "possessive") == _tokens(
            "Ospedale Sant'Andrea", "plain"
        )

    def test_plain_is_unchanged_by_the_new_machinery(self):
        assert _tokens("Queen's Hospital", "plain") == ["queen", "s", "hospital"]


class TestAdditiveInvariant:
    """A richer rule may only ever recover a pair, never demote one.

    The guarantee is **within a single table**, and the distinction matters.
    Rebuilding a table under a new rule changes the vocabulary and the total,
    so every token's relative frequency shifts a little and no strict
    inequality can hold across two differently-built tables. Whether a
    migration demotes anything is a *benchmark* question, answered by running
    Kano and London, not an invariant assertable here — asserting it was an
    overstatement these tests caught.
    """

    def test_tokens_are_a_superset_of_plain(self):
        for name in NAMES:
            assert set(_tokens(name, "plain")) <= set(_tokens(name, "possessive"))

    def test_distinctiveness_never_falls_below_the_plain_reading(self):
        # One table, two readings. Possessive tokens are a superset, so the
        # shared set can only grow and the max over it can only rise.
        table = _table("possessive")
        for a, b in PAIRS:
            rich = shared_name_distinctiveness(a, b, table)
            plain_shared = set(_tokens(a, "plain")) & set(_tokens(b, "plain"))
            plain_best = max(
                (table.distinctiveness(t) for t in plain_shared), default=0.0
            )
            assert rich >= plain_best - 1e-9, f"{a!r} vs {b!r}: {plain_best} -> {rich}"

    def test_token_similarity_never_falls_below_the_plain_reading(self):
        # The half that actually broke. `weighted_token_sim` is a ratio, so a
        # one-sided extra token inflates the union: "St Mary Hospital" against
        # "St Mary's Hospital" fell 0.763 -> 0.563 until the comparator scored
        # under BOTH rules on the same table and took the better.
        table = _table("possessive")
        for a, b in PAIRS:
            rich = table.weighted_token_sim(a, b)
            plain_only = table._token_sim(a, b, "plain", None)
            assert rich >= plain_only - 1e-9, f"{a!r} vs {b!r}: {plain_only} -> {rich}"

    def test_the_mixed_form_pair_that_regressed_is_pinned(self):
        # Only one side carries the possessive. Under the possessive
        # tokenisation alone this pair loses; the max-over-rules is what saves
        # it, so score it both ways and assert the better one wins.
        table = _table("possessive")
        a, b = "St Mary Hospital", "St Mary's Hospital"
        assert table.weighted_token_sim(a, b) >= table._token_sim(a, b, "plain", None)
        assert table.weighted_token_sim(a, b) >= table._token_sim(a, b, "possessive", None)

    def test_the_pair_the_rule_exists_to_recover(self):
        table = _table("possessive")
        a, b = "Queens Hospital", "Queen's Hospital"
        plain_shared = set(_tokens(a, "plain")) & set(_tokens(b, "plain"))
        plain_best = max((table.distinctiveness(t) for t in plain_shared), default=0.0)
        assert shared_name_distinctiveness(a, b, table) > plain_best


class TestPhraseDistinctiveness:
    """A name can be distinctive as a phrase while every token is ordinary.

    `london`, `bridge` and `hospital` are each common; `london bridge` is not.
    The corpus separates the two cases with no curation, which is the whole
    reason this is a frequency table and not a stop-list.
    """

    def _place(self):
        return TokenFrequencyTable.default(domain="place")

    def test_the_shipped_place_table_has_a_phrase_companion(self):
        assert self._place().phrases is not None

    def test_phrase_table_agrees_with_its_unigram_table_on_tokenisation(self):
        # A phrase assembled under one rule cannot be looked up in counts
        # accumulated under another. `default()` raises rather than allow it.
        table = self._place()
        assert table.phrases.token_rule == table.token_rule

    def test_generic_type_phrases_stay_common(self):
        table = self._place()
        for name in ("General Hospital", "Primary Health Centre"):
            assert table.phrase_distinctiveness(name, name) < 0.75

    def test_distinctive_name_phrases_are_rare(self):
        table = self._place()
        for name in ("London Bridge Hospital", "King's College Hospital"):
            assert table.phrase_distinctiveness(name, name) >= 0.75

    def test_an_unseen_phrase_scores_zero_not_a_default_rarity(self):
        # The `healthpost` failure at phrase scale: an unseen phrase must not
        # read as maximally distinctive because the table has never priced it.
        table = self._place()
        assert table.phrase_distinctiveness("Zzqq Wwxx Hospital", "Zzqq Wwxx Hospital") == 0.0

    def test_no_shared_phrase_scores_zero(self):
        table = self._place()
        assert table.phrase_distinctiveness("Alpha Hospital", "Beta Clinic") == 0.0

    def test_absent_or_non_population_phrase_table_is_silent(self):
        # A runtime-built table must never clear a gate on phrase evidence.
        local = TokenFrequencyTable.from_corpus(["London Bridge Hospital"] * 5)
        assert local.phrase_distinctiveness("London Bridge Hospital",
                                            "London Bridge Hospital") == 0.0

    def test_the_gate_is_additive_over_the_phrase_measure(self):
        # max, never replace: the phrase measure may recover a pair, never
        # demote one whose tokens already cleared.
        table = self._place()
        for a, b in PAIRS:
            token_only = max(
                (table.distinctiveness(t)
                 for t in name_tokens(a, table.token_rule) & name_tokens(b, table.token_rule)),
                default=0.0,
            )
            assert shared_name_distinctiveness(a, b, table) >= token_only - 1e-9


class TestPhraseGateSafety:
    """The defect the gate exists to prevent must survive the new evidence."""

    def test_two_general_hospitals_still_abstain(self):
        from arche.resolve import reconcile

        edges = reconcile(
            [{"name": "General Hospital", "lat": 12.00, "lon": 8.50}],
            [{"name": "General Hospital", "lat": 12.04, "lon": 8.50}],
            entity="place",
        )["matches"]
        assert edges and edges[0]["decision"] == "review"

    def test_a_distinctive_pair_still_merges(self):
        from arche.resolve import reconcile

        edges = reconcile(
            [{"name": "Gyaranya Health Post", "lat": 12.00, "lon": 8.50}],
            [{"name": "Gyaranya Health Post", "lat": 12.04, "lon": 8.50}],
            entity="place",
        )["matches"]
        assert edges and edges[0]["decision"] == "match"

    def test_the_phrase_table_is_named_in_the_pin(self):
        # A phrase table is a scoring input; a rebuild must be visible in every
        # decision id it touched rather than changing results silently.
        from arche.resolve import reconcile

        result = reconcile(
            [{"name": "London Bridge Hospital", "lat": 51.5050, "lon": -0.0870}],
            [{"name": "London Bridge Hospital", "lat": 51.5052, "lon": -0.0871}],
            entity="place",
        )
        assert "+phrases@sha256:" in result["pins"]["tf"]
