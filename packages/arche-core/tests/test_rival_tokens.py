# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Each side carries a distinctive token the other lacks.

One retailer lists a rug by product code, another by design name, and everything
else agrees -- collection, size, shape, colour, material::

    A: SAFAVIEH Antiquity Collection 4'6" x 6'6" Oval Blue AT21E ... Wool Area Rug
    B: SAFAVIEH Antiquity Bethanie Traditional Wool Area Rug, Blue/Beige, 4'6" x 6'6" Oval

`at21e` and `bethanie` are two different rugs. Measured on 600 cross-retailer
offer pairs, that shape was **41 of 43** false merges the `home_goods`
vocabulary could not reach, and no word list fixes it -- design names are not
enumerable.

**The mutual requirement is the safety property.** One side carrying a rare
token the other lacks means almost nothing; retailers write titles at different
lengths and the terser listing of a true pair is missing tokens constantly. Two
sides *each* carrying their own rare token is different: both are identifying
something, and they are identifying different things.

Three refinements, each forced by a measured regression on the 600-pair block:

1. **Corpus-relative rarity.** A hardcoded 0.75 floor is unreachable for a
   self-calibrated table -- the rarest token in that corpus scores 0.861, and
   the two identifiers score 0.721 and 0.706. `code_rarity` hit the same wall
   and solved it the same way.
2. **Spelling variants are not rivals.** `panels` against `panel` and
   `showerscape` against `scape` were refuting true pairs that agreed on
   everything.
3. **A shared distinctive token wins.** `Kingston Brass KB241KL ... Spout Reach`
   against `Kingston Brass KB241KL Knight ...` shares a product code that
   identifies the item outright; `spout` against `knight` is two descriptions of
   one thing. Without this the rule refuted 45 true pairs to remove 23 false.

**Its measured limit is recorded in the final class.** In a catalogue-sized
self-calibrated corpus, `spout` scores 0.766 and `at21e` scores 0.721 -- an
ordinary English word rarer than a product code. Rarity alone cannot separate
them, and arche ships no general-English frequency table that could.
"""

from __future__ import annotations

import pytest
from arche.resolve import TokenFrequencyTable
from arche.resolve._gate import (
    DISTINCTIVE_FLOOR,
    _distinctiveness_ceiling,
    rival_distinctive_tokens,
)

RUG_A = ('SAFAVIEH Antiquity Collection 4\'6" x 6\'6" Oval Blue AT21E Handmade '
         "Traditional Oriental Premium Wool Area Rug")
RUG_B = ("SAFAVIEH Antiquity Bethanie Traditional Wool Area Rug, Blue/Beige, "
         '4\'6" x 6\'6" Oval')

SCREEN_A = "Oriental Furniture 6 ft. Tall Eudes Shoji Screen - Black - 3 Panels"
SCREEN_B = ("Oriental Furniture 6 Ft Tall Cherry Blossom Shoji Screen, Black, "
            "3 Panels")

FAUCET_A = ("Kingston Brass KB241KL Tub and Shower Faucet, Polished Chrome "
            "5-Inch Spout Reach")
FAUCET_B = "Kingston Brass KB241KL Knight Tub and Shower Faucet, Polished Chrome"


@pytest.fixture(scope="module")
def tf():
    """A catalogue-shaped corpus, so rarity means what it means in one.

    Built from the titles under test plus filler that makes the shared words
    ordinary, which is exactly the situation the rule has to work in.
    """
    # The filler has to carry the *shared* tokens, dimensions included. A first
    # version left `4'6"` out, so the two rugs shared a rare measurement, the
    # shared-token suppression fired, and the rule correctly stayed quiet -- on
    # a corpus that does not exist. A catalogue with one rug in it is not a
    # catalogue, and a fixture that is not one tests the wrong engine.
    filler = [
        "SAFAVIEH Antiquity Traditional Wool Area Rug, Blue/Beige, 4'6\" x 6'6\" Oval",
        "SAFAVIEH Heritage Traditional Wool Area Rug, Red/Black, 4'6\" x 6'6\" Round",
        "SAFAVIEH Antiquity Collection Handmade Oriental Premium Wool Area Rug Blue Oval",
        "Oriental Furniture 6 ft. Tall Shoji Screen - Black - 3 Panels",
        "Oriental Furniture 6 Ft Tall Shoji Screen, Black, 3 Panels",
        "Kingston Brass Tub and Shower Faucet, Polished Chrome 5-Inch Spout Reach",
        "Kingston Brass Tub and Shower Faucet, Polished Chrome",
    ] * 40
    return TokenFrequencyTable.from_corpus(
        [RUG_A, RUG_B, SCREEN_A, SCREEN_B, FAUCET_A, FAUCET_B, *filler])


class TestItFiresOnRivalIdentifiers:

    def test_a_product_code_against_a_design_name(self, tf):
        """The shape worth 41 of 43 residual false merges."""
        assert rival_distinctive_tokens(RUG_A, RUG_B, tf) == 0.0

    def test_two_pattern_names(self, tf):
        """`Eudes` against `Cherry Blossom`, everything else identical. No
        vocabulary enumerates design names; this rule does not need one."""
        assert rival_distinctive_tokens(SCREEN_A, SCREEN_B, tf) == 0.0

    def test_it_only_ever_refutes(self, tf):
        """0.0 or None, never 1.0. Declared at weight 0.0 with
        `refutes_below`, so it can hold a pair back and never push one up."""
        for a, b in [(RUG_A, RUG_B), (RUG_A, RUG_A), (FAUCET_A, FAUCET_B)]:
            assert rival_distinctive_tokens(a, b, tf) in (0.0, None)


class TestItStaysQuiet:

    def test_identical_titles(self, tf):
        assert rival_distinctive_tokens(RUG_A, RUG_A, tf) is None

    def test_one_sided_verbosity(self, tf):
        """A terse listing is not a contradiction. This is the case the mutual
        requirement exists to protect, and it is most of real catalogue data."""
        terse = "SAFAVIEH Antiquity Wool Area Rug"
        assert rival_distinctive_tokens(RUG_A, terse, tf) is None

    def test_a_shared_product_code_outranks_unshared_words(self, tf):
        """Both name `KB241KL`. One describes the spout, the other names the
        model -- two descriptions of one item, not two items."""
        assert rival_distinctive_tokens(FAUCET_A, FAUCET_B, tf) is None

    def test_a_plural_is_not_a_rival(self, tf):
        """`3 Panels` against `3 Panel`. One word, two spellings, and it was
        refuting true pairs that agreed on everything else."""
        a = "Oriental Furniture 6 ft. Tall Eudes Shoji Screen - Black - 3 Panels"
        b = "Oriental Furniture 6 ft. Tall Eudes Shoji Screen - Black - 3 Panel"
        assert rival_distinctive_tokens(a, b, tf) is None

    def test_a_compound_split_is_not_a_rival(self, tf):
        """`Showerscape` against `Shower Scape`."""
        a = "Kingston Brass K117C8 Designer Trimscape Showerscape 17-Inch Shower Arm"
        b = 'Kingston Brass K117C8 Shower Scape 17" Shower Arm'
        assert rival_distinctive_tokens(a, b, tf) is None


class TestCorpusRelativeRarity:
    """A constant floor is the wrong instrument for a self-calibrated table."""

    def test_the_ceiling_is_below_one_for_a_catalogue_corpus(self, tf):
        ceiling = _distinctiveness_ceiling(tf)
        assert 0.0 < ceiling <= 1.0

    def test_a_hardcoded_floor_would_miss_the_target_tokens(self, tf):
        """`at21e` scores 0.721 against a 0.75 constant. Scoring identifiers
        against a constant a small corpus cannot reach is the failure
        `code_rarity` documents: recall 0.2197 -> 0.0948."""
        assert tf.distinctiveness("at21e") < DISTINCTIVE_FLOOR
        assert rival_distinctive_tokens(RUG_A, RUG_B, tf) == 0.0

    def test_the_ceiling_is_cached_on_the_table(self, tf):
        """A linear scan per candidate pair, over thousands of pairs, to
        recompute a constant."""
        _distinctiveness_ceiling(tf)
        assert getattr(tf, "_rival_ceiling", None) is not None

    def test_a_degenerate_table_cannot_drive_the_threshold_to_zero(self):
        """Which would refute every pair carrying any unshared token at all."""
        flat = TokenFrequencyTable.from_corpus(["a b c"] * 5)
        assert _distinctiveness_ceiling(flat) >= 0.2

    def test_a_stricter_floor_is_declarable(self, tf):
        assert rival_distinctive_tokens(RUG_A, RUG_B, tf, floor=1.5) is None


class TestThePackWiring:

    def test_home_goods_declares_it(self):
        from arche.resolve import ENTITY_PACKS

        rival = [s for s in ENTITY_PACKS["product_home_goods"]
                 if s["kind"] == "rival"]
        assert len(rival) == 1
        assert rival[0]["weight"] == 0.0, "it must not contribute to the score"
        assert rival[0]["refutes_below"] == 0.5

    def test_only_product_packs_declare_it(self):
        """It changes what agreement means, so a pack adopting it is a separate
        and separately-measured decision -- never a side effect.

        Two packs declare it today. `product_home_goods`, where it was built and
        measured; and `product_grocery`, where own-label was the failure it had
        to survive -- `Tesco Chopped Tomatoes 400g` and `Sainsbury's Chopped
        Tomatoes 400g` matched at 0.735 without it, and they are two different
        products with the same net contents. The retailer name is the only
        separator and it is exactly a rival token.

        `place`, `person`, `organisation` and `artist` have published numbers
        this would move.
        """
        from arche.resolve import ENTITY_PACKS

        adopted = {name for name, specs in ENTITY_PACKS.items()
                   if any(s.get("kind") == "rival" for s in specs)}
        assert adopted == {"product_home_goods", "product_grocery"}

    def test_it_needs_a_table_and_says_so(self):
        """`tftoken` raises the same way. A comparator whose whole job is
        deciding what counts as rare cannot run without the table that decides
        it, and failing loudly beats scoring every pair as not-comparable.

        `block=None` because the default blocker produces no candidate pair for
        a rival-only comparator set, and a comparator that never runs cannot
        raise -- which would pass this test while proving nothing.
        """
        from arche.resolve import reconcile

        with pytest.raises(ValueError, match="rival"):
            reconcile([{"id": "a", "name": RUG_A}], [{"id": "b", "name": RUG_B}],
                      [{"field": "name", "kind": "rival", "weight": 0.0}],
                      id_field="id", block=None)


class TestWhatItCannotDo:
    """The measured limit, recorded rather than implied.

    On the 600-pair block the rule takes `home_goods` from 43 false merges to
    21 and precision 0.736 to 0.802 -- but it also moves 35 true pairs from
    `match` to `review`, so F1 falls. Those pairs are still surfaced with full
    evidence; whether that trade is right depends on whether a wrong price
    comparison costs more than a human glance, which is a customer's question
    and not arche's.
    """

    def test_an_ordinary_word_can_outrank_a_product_code(self, tf):
        """The root limitation. In a catalogue-sized self-calibrated corpus
        `spout` is rarer than `at21e`, because rarity here is a fact about this
        catalogue rather than about English.

        Separating them needs a general-vocabulary reference, and arche ships
        no general-English frequency table -- the shipped ones are places,
        person names, organisations and artists. That is the gap to close before
        this rule can be tightened further.
        """
        corpus = ["Tub and Shower Faucet Polished Chrome"] * 50 + [
            "Kingston Brass Tub Shower Faucet 5-Inch Spout Reach",
            "SAFAVIEH Antiquity Oval Blue AT21E Wool Area Rug",
        ]
        table = TokenFrequencyTable.from_corpus(corpus)
        assert table.distinctiveness("spout") >= table.distinctiveness("at21e")
