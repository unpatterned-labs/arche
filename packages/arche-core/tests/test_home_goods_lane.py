# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The `home_goods` product category, and what it does and does not fix.

**Why it exists.** Pointing `product_electronics` at a furniture or bedding
catalogue silently disables both of its safety mechanisms. `code` finds no model
numbers in a home-goods title, and `spec` is `category="electronics"`, so it
looks for GB and GHz while `King`, `Ivory`, `Plush` and `3 Panels` mean nothing
to it. What survives is title similarity with a rarity gate, which merges
variants of one family into a single "product" and produces the unsafe price
comparison this lane exists to prevent.

**Measured, on 600 cross-retailer pairs** from a real offer feed (Amazon against
Walmart, a shared product id as truth):

                        blocking R   auto P   auto R      F1   false merges
    product_electronics      50.2%   0.8621   0.1250   0.2183        12
    product_home_goods       84.2%   0.7362   0.2000   0.3145        43

**Read that honestly.** F1 and recall improve substantially and the individual
failure shapes below are genuinely fixed. Precision does not: it falls from
0.862 to 0.736, because the better candidate generation surfaces a dense cluster
of near-variants the vocabulary cannot separate — SAFAVIEH rugs of one
collection and size differing only by a design name (`Bethanie`, `Cromwell`,
`Lancaster`). For a price-comparison use case precision is the measure that
matters, so this category is **not yet a net win there** and is marked
experimental accordingly.

What it does fix is pinned below, one class at a time, so the parts that work
are not lost while the remaining cluster is worked on.
"""

from __future__ import annotations

import pytest
from arche.resolve import reconcile
from arche.resolve._productcode import (
    PRODUCT_CATEGORIES,
    compare_specs,
    extract_attributes,
    extract_specs,
)


def decide(name_a: str, name_b: str, entity: str = "product_home_goods") -> str:
    edges = reconcile([{"id": "a", "name": name_a}], [{"id": "b", "name": name_b}],
                      entity=entity, id_field="id")["matches"]
    return edges[0]["decision"] if edges else "not_surfaced"


class TestTheCategoryIsRegistered:

    def test_it_exists(self):
        assert "home_goods" in PRODUCT_CATEGORIES

    def test_length_is_identity_bearing_here_and_not_in_electronics(self):
        """The cheapest of the fixes. A 6 ft and a 7 ft room divider are
        different products; `electronics` already extracts `ft` and simply never
        asks about it, because a foot does not identify a hard drive."""
        assert "ft" in PRODUCT_CATEGORIES["home_goods"].identity_units
        assert "ft" not in PRODUCT_CATEGORIES["electronics"].identity_units


class TestCategoricalAttributes:
    """`identity_units` only reaches a number bound to a unit. The attributes
    that distinguish home goods are words."""

    def test_size_and_colour_come_out(self):
        got = extract_attributes(
            "LCM Microfiber Down Alternative Blanket, King, Blue", "home_goods")
        assert got["size"] == {"king"}
        assert got["colour"] == {"blue"}

    def test_a_dual_size_registers_as_both(self):
        """`Full/Queen` is one item that genuinely fits both, so it must agree
        with a listing naming either."""
        got = extract_attributes("Blanket, Full/Queen, Ivory", "home_goods")
        assert {"full", "queen"} <= got["size"]
        assert compare_specs("Blanket, Full/Queen, Ivory",
                             "Blanket, Queen, Ivory", "home_goods") == 1.0

    def test_a_term_inside_a_longer_word_does_not_fire(self):
        """Space-padded substring matching, so `king` is not found in
        `Kingston` and a brand name does not become a bed size."""
        assert "size" not in extract_attributes(
            "Kingston Cotton Throw", "home_goods")

    def test_shape_separates_two_rugs_of_one_size(self):
        got = extract_attributes('Wool Area Rug, Blue, 7\'6" x 9\'6" Oval',
                                 "home_goods")
        assert got["shape"] == {"oval"}

    def test_other_categories_are_untouched(self):
        """Electronics, food and bibliographic declare no `identity_attributes`,
        so this machinery is inert for them and their numbers cannot move."""
        for category in ("electronics", "food", "bibliographic"):
            assert extract_attributes("Blanket, King, Blue", category) == {}


class TestTheAsymmetryRule:
    """One side names a variant attribute and the other names none of it.

    Everywhere else in arche an absent field is missing evidence rather than a
    disagreement. Here it is the commonest way a retailer catalogue misleads: a
    *variant* page and a *family* page describe different purchasable things in
    near-identical words. Six of the twelve measured false merges were this.
    """

    VARIANT = "LCM Home Fashions Microfiber Down Alternative Blanket, King, Blue"
    FAMILY = "LCM Home Fashions Microfiber Plush Down Alternative Blanket"

    def test_the_flag_is_on_for_home_goods_only(self):
        assert PRODUCT_CATEGORIES["home_goods"].asymmetry_refutes is True
        assert PRODUCT_CATEGORIES["electronics"].asymmetry_refutes is False

    def test_a_variant_page_does_not_agree_with_a_family_page(self):
        assert compare_specs(self.VARIANT, self.FAMILY, "home_goods") == 0.0

    def test_electronics_called_it_a_match_and_home_goods_does_not(self):
        """The regression, end to end through the real engine."""
        assert decide(self.VARIANT, self.FAMILY, "product_electronics") == "match"
        assert decide(self.VARIANT, self.FAMILY) == "review"

    def test_two_variant_pages_agreeing_are_still_fine(self):
        """The rule must not refuse everything it touches."""
        assert compare_specs("Blanket, King, Blue", "Blanket, King, Blue",
                             "home_goods") == 1.0


class TestNumericDisagreement:

    def test_a_six_foot_screen_is_not_a_seven_foot_one(self):
        a = "Oriental Furniture 7 ft. Tall Double Cross Shoji Screen - Honey - 3 Panels"
        b = "Oriental Furniture 6 ft. Tall Double Cross Shoji Screen - Natural - 3 Panel"
        assert compare_specs(a, b, "home_goods") == 0.0
        assert decide(a, b, "product_electronics") == "match"
        assert decide(a, b) == "review"

    def test_panel_counts_agree_across_singular_and_plural(self):
        assert extract_specs("Shoji Screen 3 Panels", "home_goods") == {"panel": {3.0}}
        assert extract_specs("Shoji Screen 3 Panel", "home_goods") == {"panel": {3.0}}

    def test_a_bundle_is_not_the_single_item(self):
        """The multipack relationship: a listing containing the product but
        changing the sellable unit. Direct price comparison is wrong."""
        assert compare_specs("Milano 1-Piece Patio Armchair",
                             "Milano 2 Pieces Folding Armchairs",
                             "home_goods") == 0.0


class TestWhatItStillGetsWrong:
    """Recorded rather than hidden. These are the residual cluster and the
    reason this category is not yet a net precision win."""

    def test_a_design_name_is_not_caught(self):
        """Same collection, same size, same colour, same panel count. The only
        difference is a pattern name, which no closed vocabulary enumerates.

        The general fix is an asymmetric-distinctive-token rule -- A carries a
        rare token B lacks and B carries a rare token A lacks -- not a longer
        word list. Until that exists this pair merges.
        """
        a = "Oriental Furniture 6 ft. Tall Eudes Shoji Screen - Black - 3 Panels"
        b = "Oriental Furniture 6 Ft Tall Cherry Blossom Shoji Screen, Black, 3 Panels"
        assert compare_specs(a, b, "home_goods") == 1.0
        assert decide(a, b) == "match"

    def test_a_design_name_against_a_product_code_is_not_caught(self):
        """The dominant residual shape, and the one that costs the precision.

        **41 of the 43 false merges are this**, all one vendor. Amazon lists the
        rug by product code and Walmart lists it by design name, and everything
        else agrees: same collection, size, shape, colour and material.

        A carries `at21e`, B carries `bethanie`. Neither side shares the other's
        distinctive token, which is evidence of two different rugs -- and no
        comparator reads it that way today. That is one mechanism worth 41 of 43
        errors, and it is a rule rather than a longer word list.

        Titles verbatim from the feed. An earlier version of this test
        hand-trimmed them, dropped `Wool` from A, and manufactured an asymmetry
        the real data does not have -- so it passed while testing nothing.
        """
        a = ('SAFAVIEH Antiquity Collection 4\'6" x 6\'6" Oval Blue AT21E Handmade '
             "Traditional Oriental Premium Wool Area Rug")
        b = ("SAFAVIEH Antiquity Bethanie Traditional Wool Area Rug, Blue/Beige, "
             '4\'6" x 6\'6" Oval')
        assert compare_specs(a, b, "home_goods") == 1.0

    def test_a_pattern_word_can_be_read_as_a_size(self):
        """`Double Cross` is a lattice pattern; `double` is also a bed size.
        Harmless where both sides carry it, which is why it survives -- but it
        is a real ambiguity in the vocabulary and it is written down.
        """
        assert extract_attributes("Double Cross Shoji Screen", "home_goods")["size"] \
            == {"double"}


class TestElectronicsIsUnchanged:
    """The whole extension is opt-in per category. `test_product_lane.py` holds
    the Abt-Buy figures; these are the cheap guards that the shared machinery
    did not shift underneath them."""

    def test_specs_still_extract(self):
        assert extract_specs("Sony 16GB 1080p 3.5 inch player", "electronics") == {
            "gb": {16.0}, "p": {1080.0}, "inch": {3.5}}

    def test_the_new_units_do_not_fire_for_electronics(self):
        got = extract_specs("3 Piece Speaker Set 16GB", "electronics")
        assert got.get("gb") == {16.0}
        assert "piece" not in PRODUCT_CATEGORIES["electronics"].identity_units

    def test_a_quantity_unit_is_still_not_a_code_for_electronics(self):
        assert PRODUCT_CATEGORIES["electronics"].quantities_are_specs is False
