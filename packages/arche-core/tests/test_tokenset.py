# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""A long title is not a long name, and the name comparators know it are not.

`name`, `placename` and the rest are sequence-similarity measures tuned for two
to four tokens of personal or place name. A retail product title is fifteen
tokens, and two systems describing one product vary hardest on exactly the two
things a sequence measure punishes: **word order and level of detail**.

Measured on 400 cross-retailer offer pairs against hard negatives -- same brand,
different product -- each measure alone at its own best threshold::

    containment    thr 0.40   P 0.830   R 0.890   F1 0.859
    `name`         thr 0.62   P 0.593   R 0.895   F1 0.713

The separation is the reason rather than the headline::

                    true p10    hard-negative p90
    `name`            0.617          0.840        <- overlapping
    containment       0.381          0.462        <- separable

`name` cannot be thresholded on this data at all: its tenth-percentile true pair
scores *below* its ninetieth-percentile false one. Any cut either keeps most of
the negatives or throws away most of the positives, which is why the pack's gate
sits high and recall collapses.
"""

from __future__ import annotations

import pytest
from arche.resolve import ENTITY_PACKS, TokenFrequencyTable, reconcile
from arche.resolve._gate import tokenset_similarity

VERBOSE = ("SAFAVIEH Antiquity Collection Handmade Traditional Oriental "
           "Premium Wool Area Rug Blue Oval")
TERSE = "SAFAVIEH Antiquity Wool Area Rug Blue"


class TestTheMeasure:

    def test_identical_text_is_one(self):
        assert tokenset_similarity("Wool Area Rug", "Wool Area Rug") == 1.0

    def test_word_order_does_not_matter(self):
        """The first thing two catalogues disagree about."""
        assert tokenset_similarity("Blue Wool Area Rug",
                                   "Area Rug Wool Blue") == 1.0

    def test_a_terser_listing_is_not_a_weaker_claim(self):
        """Divided by the smaller bag, not the union. Jaccard would score this
        0.5 and punish a retailer for writing a longer title about the same
        rug; containment asks whether everything the terser side says is also
        said by the other."""
        assert tokenset_similarity(VERBOSE, TERSE) == 1.0

    def test_unrelated_text_is_zero(self):
        assert tokenset_similarity("Blue Wool Rug", "Stainless Steel Sink") == 0.0

    def test_partial_overlap_is_proportional(self):
        got = tokenset_similarity("Blue Wool Area Rug", "Red Wool Area Rug")
        assert got == pytest.approx(0.75)

    def test_empty_text_is_zero_rather_than_an_error(self):
        assert tokenset_similarity("", "Wool Area Rug") == 0.0
        assert tokenset_similarity("Wool Area Rug", "") == 0.0

    def test_it_is_symmetric(self):
        assert (tokenset_similarity(VERBOSE, TERSE)
                == tokenset_similarity(TERSE, VERBOSE))


class TestWhereItBeatsTheNameComparator:
    """The reason it exists, stated as the comparison that produced it."""

    def test_reordered_detail_survives(self):
        """Two real listings of one rug, written by two retailers."""
        a = ('SAFAVIEH Antiquity Collection 4\'6" x 6\'6" Oval Blue AT21E '
             "Handmade Traditional Oriental Premium Wool Area Rug")
        b = ("SAFAVIEH Antiquity Traditional Wool Area Rug, Blue, "
             '4\'6" x 6\'6" Oval')
        assert tokenset_similarity(a, b) > 0.8

    def test_a_shared_family_still_scores_high(self):
        """Its known weakness, recorded rather than implied: containment cannot
        tell a variant from its family, because the family's words are a subset
        of the variant's. That is what `spec` and `rival` are for, and it is why
        this must never be the only signal in a pack."""
        family = "LCM Microfiber Plush Down Alternative Blanket"
        variant = "LCM Microfiber Down Alternative Blanket King Blue"
        assert tokenset_similarity(family, variant) > 0.7


class TestTheComparatorKind:

    def _run(self, name_a, name_b, weight=3.0):
        a = [{"id": "a", "name": name_a}]
        b = [{"id": "b", "name": name_b}]
        tf = TokenFrequencyTable.from_corpus([name_a, name_b] * 5)
        edges = reconcile(
            a, b, [{"field": "name", "kind": "tokenset", "weight": weight}],
            tf=tf, id_field="id", block=None)["matches"]
        return edges[0] if edges else None

    def test_it_scores_a_pair(self):
        edge = self._run(VERBOSE, TERSE)
        assert edge is not None
        assert edge["evidence"]["name"] == 1.0

    def test_a_missing_field_is_not_comparable(self):
        """The rule every comparator here follows: absent is not a
        disagreement."""
        tf = TokenFrequencyTable.from_corpus([VERBOSE] * 5)
        edges = reconcile(
            [{"id": "a", "name": VERBOSE}], [{"id": "b"}],
            [{"field": "name", "kind": "tokenset", "weight": 3.0}],
            tf=tf, id_field="id", block=None)["matches"]
        assert edges == []

    def test_it_has_a_note_an_agent_can_read(self):
        from arche.resolve import COMPARATOR_NOTES

        assert "tokenset" in COMPARATOR_NOTES
        assert len(COMPARATOR_NOTES["tokenset"]) > 40


class TestNoPackAdoptsItYet:
    """It changes what agreement means. Putting it in a pack moves that pack's
    published numbers, so it is a separate and separately-measured decision --
    the same rule `test_discriminator_veto.py` enforces for refutation."""

    def test_no_shipped_pack_declares_it(self):
        for name, specs in ENTITY_PACKS.items():
            assert not any(s.get("kind") == "tokenset" for s in specs), name

    def test_it_is_reachable_by_declaration(self):
        """Available to a caller who passes `comparators=` today, which is how
        a new comparator earns its way into a pack: measured first."""
        edge = self._reachable()
        assert edge is not None

    def _reachable(self):
        tf = TokenFrequencyTable.from_corpus([VERBOSE, TERSE] * 5)
        edges = reconcile(
            [{"id": "a", "name": VERBOSE}], [{"id": "b", "name": TERSE}],
            [{"field": "name", "kind": "tokenset", "weight": 3.0}],
            tf=tf, id_field="id", block=None)["matches"]
        return edges[0] if edges else None
