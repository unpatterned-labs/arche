# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The `product_grocery` pack, and the gap it was built to close.

The `food` product category has shipped since 0.5 with extraction tests and no
pack. Its own docstring says why:

    NO MATCHING BENCHMARK. Its extraction behaviour is tested; its matching
    accuracy is not, because no open grocery corpus with complete ground truth
    is available to this project. Do not read it as measured. The gate for
    promoting it out of this state is a labelled corpus, the same bar the
    electronics lane had to clear.

A corpus became available: five UK supermarkets, a `gtin` on every row. A GTIN
is an **external standard**, not one vendor's internal key, which makes it
better truth than anything else in this repository -- nobody assigned it with an
interest in how matching turns out. It is client data and stays outside the
repo; `datasets/bench_product_matching.py` takes a path so the harness can ship
without it.

**What makes grocery its own lane** is `quantities_are_specs`. Under the
electronics rules `415g` is a *code candidate* -- a model number. For a
supermarket SKU net contents are the identity: `Tesco Almonds 200G` and `Tesco
Almonds 500G` are two products a shopper chooses between, and the weight must
refute rather than identify. Reading a dose or a pack size as a model number is
the failure an adversarial review of the product lane called out by name.
"""

from __future__ import annotations

import pytest
from arche.resolve import ENTITY_PACKS, reconcile, describe_pack
from arche.resolve._productcode import (
    PRODUCT_CATEGORIES,
    compare_specs,
    extract_product_code_candidates,
    extract_specs,
)


#: Filler so the frequency table is a catalogue rather than two rows.
#:
#: A two-record self-calibrated table is degenerate -- every token is equally
#: rare, `tftoken` collapses to 0.38, and the score lands at 0.505. That is
#: under the default return floor (threshold 0.7 minus a 0.15 review margin), so
#: the edge is **dropped entirely instead of demoted**, and a reviewer never
#: sees the conflict that caused it. The veto tests name that outcome as
#: strictly worse than `review`.
#:
#: It is a property of the table, not of the pack, and a test that hit it was
#: measuring the fixture. Real runs have a catalogue behind them, so the fixture
#: has one too.
SHELF = [
    "Tesco Almonds 200G", "Tesco Almonds 500G", "Tesco Cashews 200G",
    "Tesco Walnuts 200G", "Sainsbury's Almonds 200g", "Heinz Baked Beans 415g",
    "Heinz Baked Beanz 415G", "Tesco Chopped Tomatoes 400g",
    "Sainsbury's Chopped Tomatoes 400g", "Coca-Cola Zero 330ml",
    "Tesco Semi Skimmed Milk 2L", "Tesco Semi Skimmed Milk 1L",
] * 12


def decide(name_a: str, name_b: str, entity: str = "product_grocery") -> str:
    from arche.resolve import TokenFrequencyTable, reconcile

    table = TokenFrequencyTable.from_corpus([*SHELF, name_a, name_b])
    edges = reconcile([{"id": "a", "name": name_a}], [{"id": "b", "name": name_b}],
                      ENTITY_PACKS[entity], tf=table, id_field="id",
                      block=None)["matches"]
    return edges[0]["decision"] if edges else "not_surfaced"


class TestThePackExists:

    def test_it_is_registered(self):
        assert "product_grocery" in ENTITY_PACKS

    def test_it_reads_the_food_category(self):
        categories = {c.get("category") for c in ENTITY_PACKS["product_grocery"]
                      if c.get("category")}
        assert categories == {"food"}

    def test_it_says_what_it_is_for(self):
        purpose = describe_pack("product_grocery")["purpose"]
        assert "net contents" in purpose

    def test_it_declares_the_refutation(self):
        spec = [c for c in ENTITY_PACKS["product_grocery"] if c["kind"] == "spec"]
        assert spec and spec[0]["refutes_below"] == 0.5


class TestNetContentsAreIdentityNotAModelNumber:
    """The whole reason grocery is not electronics."""

    def test_quantities_are_specifications_here(self):
        assert PRODUCT_CATEGORIES["food"].quantities_are_specs is True
        assert PRODUCT_CATEGORIES["electronics"].quantities_are_specs is False

    def test_a_pack_weight_is_not_read_as_a_code(self):
        """`415g` as a model number is the failure this category prevents."""
        codes = extract_product_code_candidates("Heinz Baked Beans 415g", "food")
        assert not any("415" in c for c in codes), codes

    def test_the_same_string_is_a_code_candidate_for_electronics(self):
        """The contrast, so the category is doing the work and not a global
        rule that would break the measured electronics lane."""
        codes = extract_product_code_candidates("Sony Player 16gb", "electronics")
        assert any("16gb" in c for c in codes), codes

    def test_two_pack_sizes_are_two_products(self):
        assert compare_specs("Tesco Almonds 200G", "Tesco Almonds 500G",
                             "food") == 0.0

    def test_one_pack_size_written_twice_is_one_product(self):
        assert compare_specs("Tesco Almonds 200G", "Tesco Almonds 200g",
                             "food") == 1.0

    def test_millilitres_too(self):
        assert extract_specs("Coca-Cola Zero 330ml", "food") == {"ml": {330.0}}


class TestEndToEnd:

    def test_a_size_difference_is_held(self):
        """Same brand, same product, different pack. A price comparison between
        them is wrong and the engine must not assert the merge."""
        assert decide("Tesco Almonds 200G", "Tesco Almonds 500G") == "review"

    def test_the_same_item_at_two_retailers_can_match(self):
        assert decide("Heinz Baked Beans 415g",
                      "Heinz Baked Beanz 415G") in {"match", "review"}

    @pytest.mark.parametrize("pack", sorted(ENTITY_PACKS))
    def test_every_pack_still_answers(self, pack):
        """Adding a pack must not break the others' description surface."""
        described = describe_pack(pack)
        assert described["field_names"]


class TestWhatIsStillUnmeasured:
    """Recorded rather than implied, in the category's own tradition.

    The benchmark that justifies this pack runs on data this repository does
    not contain, so the number cannot be reproduced from a clean checkout. It
    is reported in the benchmarks page with its provenance, and these tests
    cover behaviour rather than accuracy.

    Own-label equivalence is deliberately out of scope. A Tesco value tin and an
    Aldi value tin are a *comparable basket item*, not the same product, and no
    GTIN links them. Anything claiming to match own-label across retailers is
    answering a different question and should say so.
    """

    def test_own_label_across_retailers_is_not_asserted(self):
        assert decide("Tesco Chopped Tomatoes 400g",
                      "Sainsbury's Chopped Tomatoes 400g") != "match"
