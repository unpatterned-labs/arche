# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the experimental electronics product lane.

The measurement this lane is built on, from Leipzig Abt-Buy (complete ground
truth): a regex that extracts code-looking tokens blocks candidate pairs at
0.5643 precision, which is barely better than a coin flip. Conditioned on the
document frequency of the shared code it separates almost perfectly — 0.9973 at
df 1-2, and 0.0000 at df 20+, where 503 pairs sharing `1080p` or `16gb` contain
no true match at all.

So the signal is rarity, not "looks like a model number", and the lane is a
frequency table plus the existing gate rather than a cleverer regex.
"""

from __future__ import annotations

import pytest

from arche.resolve import ENTITY_PACKS, crosswalk
from arche.resolve._gate import DISTINCTIVE_FLOOR
from arche.resolve._productcode import (
    PRODUCT_CATEGORIES,
    ProductCategory,
    build_code_table,
    code_rarity,
    compare_codes,
    compare_specs,
    extract_product_code_candidates,
    extract_specs,
    register_category,
)


class TestExtraction:
    def test_a_real_pair_of_titles(self):
        assert extract_product_code_candidates(
            "Fellowes Powershred Personal SB-97Cs Confetti Cut Shredder - 3219701"
        ) == {"sb97cs", "3219701"}

    def test_normalisation_is_load_bearing(self):
        """`SB97CS` and `SB-97Cs` must land on the same string.

        Raw-string matching finds a shared code on 44.9% of true pairs;
        normalised, 71.2%. This single step is most of the lane.
        """
        a = extract_product_code_candidates("Shredder SB97CS")
        b = extract_product_code_candidates("Shredder SB-97Cs")
        assert a & b == {"sb97cs"}

    def test_each_span_is_normalised_separately(self):
        """Two adjacent codes must not fuse into one neither source wrote."""
        assert "ab12cd34" not in extract_product_code_candidates("Widget AB12 CD34")

    def test_bare_short_numbers_are_rejected(self):
        """Prices, years and quantities are not identifiers."""
        got = extract_product_code_candidates("Sony TV 2008 $499 model KDL19M4000")
        assert "2008" not in got and "499" not in got
        assert "kdl19m4000" in got

    def test_alphabetic_tokens_are_not_codes(self):
        assert extract_product_code_candidates("Canon Digital Camera Case") == set()

    def test_stop_codes_are_dropped(self):
        """A resolution is shared by thousands of products and identifies none.

        The frequency table suppresses these anyway; the stop list means a
        *small* catalogue, where every code looks rare, cannot merge on one.
        """
        got = extract_product_code_candidates("Sony 1080p 16GB Handycam HDRCX150")
        assert "1080p" not in got
        assert {"16gb", "hdrcx150"} <= got


class TestSpecs:
    def test_units_are_read_with_their_values(self):
        assert extract_specs("Sony 16GB 3.5 inch player") == {
            "gb": {16.0}, "inch": {3.5},
        }

    def test_unit_aliases_collapse(self):
        assert extract_specs('27 in monitor')["inch"] == {27.0}

    def test_comparable_units_agreeing(self):
        assert compare_specs("Player 16GB black", "16GB Player") == 1.0

    def test_the_sku_contract(self):
        """A 16GB and a 32GB player are different purchasable products."""
        assert compare_specs("Player 16GB", "Player 32GB") == 0.0

    def test_incomparable_is_None_not_zero(self):
        """No shared identity unit is missing evidence, not disagreement."""
        assert compare_specs("Player 16GB", "Player black") is None
        assert compare_specs("Camera", "Camera") is None

    def test_non_identity_units_are_ignored(self):
        """`1080p` differing is not a variant difference under this contract."""
        assert compare_specs("TV 1080p", "TV 720p") is None


class TestRarityCalibration:
    """The bug that made the first version of this lane worse than no lane.

    `TokenFrequencyTable.distinctiveness` is `min(1, -log10(rel_freq)/5)`,
    calibrated for the million-token word corpora behind the place and person
    tables. A code vocabulary is ~2,000 documents, so the rarest possible shared
    code scored 0.6205 through it — under `DISTINCTIVE_FLOOR` — and the gate
    demoted every true product match. Recall fell from 0.2197 to 0.0948.
    """

    @pytest.fixture
    def tf(self):
        titles = [f"Widget model AB{i:04d}X" for i in range(500)]
        titles += ["Common 16GB thing"] * 20
        titles += ["Other 16GB item"] * 20
        return build_code_table(titles)

    def test_the_rarest_shared_code_clears_the_gate_floor(self, tf):
        """Regression. A code appearing once per source must be able to match.

        A shared code has document frequency >= 2 by construction, so if df 2
        cannot clear the floor the lane cannot auto-match anything.
        """
        table = build_code_table(["Widget AB0001X", "Widget AB0001X other words"])
        assert code_rarity("ab0001x", table) >= DISTINCTIVE_FLOOR

    def test_rarity_tracks_the_measured_precision_curve(self, tf):
        assert code_rarity("ab0001x", tf) == 1.0          # df 1-2 -> 0.9973
        assert code_rarity("16gb", tf) < 0.15             # df 40  -> 0.0000

    def test_an_unseen_code_is_maximally_rare(self, tf):
        assert code_rarity("zz9999q", tf) == 1.0

    def test_common_codes_score_near_zero(self, tf):
        assert code_rarity("16gb", tf) < code_rarity("ab0001x", tf)


class TestCompareCodes:
    @pytest.fixture
    def tf(self):
        return build_code_table(
            ["Cam 2595B002", "Case 2595B002"] + ["Thing 16GB"] * 20
        )

    def test_absent_on_either_side_is_None(self, tf):
        """Absent evidence refutes nothing — the rule veto_km already follows."""
        assert compare_codes("Canon Camera Case", "Canon 2595B002", tf) is None
        assert compare_codes("Canon 2595B002", "Canon Camera Case", tf) is None

    def test_present_but_unshared_is_a_disagreement_not_a_veto(self, tf):
        """0.0, left to `weight`.

        18.6% of Abt-Buy's true pairs carry codes on both sides and share none —
        accessories, bundles, retailer SKUs. A hard conflict rule would refute
        all of them, so this must not be a veto.
        """
        assert compare_codes("Cam AB123X", "Cam CD456Y", tf) == 0.0

    def test_a_rare_shared_code_scores_high(self, tf):
        assert compare_codes("Canon Case 2595B002", "Canon 2595B002 Cam", tf) == 1.0

    def test_a_common_shared_code_scores_low(self, tf):
        assert compare_codes("Player 16GB", "Recorder 16GB", tf) < 0.2

    def test_without_a_table_it_cannot_discriminate(self, tf):
        """The 0.5643-precision behaviour, pinned — this is why a table ships."""
        assert compare_codes("Player 16GB", "Recorder 16GB", None) == 1.0


class TestModularity:
    """Food, books and apparel must be a registration, not a code change."""

    def test_a_new_category_changes_the_rules(self):
        register_category(ProductCategory(
            name="_test_apparel",
            # Both length knobs must move. Electronics rejects `501` twice
            # over — once for being shorter than four characters, once for
            # being a bare number under five digits. Those thresholds exist to
            # reject prices and years in electronics titles, and they are
            # exactly wrong for apparel, where `501` and `1460` are models.
            min_code_len=3,
            min_bare_number_len=3,
            identity_units=("inch",),
            stop_codes=frozenset({"32x32"}),
        ))
        try:
            got = extract_product_code_candidates(
                "Levi's 501 Original 32x32 jeans", "_test_apparel",
            )
            assert "501" in got, "the electronics length rule would drop this"
            assert "32x32" not in got
            # The electronics rules are untouched by the registration.
            assert "501" not in extract_product_code_candidates(
                "Levi's 501 jeans", "electronics",
            )
        finally:
            PRODUCT_CATEGORIES.pop("_test_apparel", None)

    def test_identity_units_are_per_category(self):
        register_category(ProductCategory(name="_test_none", identity_units=()))
        try:
            # No identity units declared -> a capacity difference is an attribute.
            assert compare_specs("Player 16GB", "Player 32GB", "_test_none") is None
            assert compare_specs("Player 16GB", "Player 32GB", "electronics") == 0.0
        finally:
            PRODUCT_CATEGORIES.pop("_test_none", None)

    def test_an_unknown_category_raises_and_lists_what_exists(self):
        with pytest.raises(ValueError, match="unknown product category"):
            extract_product_code_candidates("x", "groceries")


class TestPack:
    def test_there_is_no_generic_product_pack(self):
        """Shipping one would overclaim.

        The evidence is a single electronics corpus. On Amazon-GoogleProducts,
        which is general merchandise, the lane moves F1 only 0.3971 -> 0.4007.
        """
        assert "product" not in ENTITY_PACKS
        assert "product_electronics" in ENTITY_PACKS

    def test_the_category_is_marked_experimental(self):
        assert PRODUCT_CATEGORIES["electronics"].experimental is True

    def test_the_pack_declares_the_sku_identity_contract(self):
        """`spec` must refute, or the lane is not resolving purchasable variants."""
        spec = next(s for s in ENTITY_PACKS["product_electronics"]
                    if s["kind"] == "spec")
        assert "refutes_below" in spec

    def test_end_to_end_in_one_call(self):
        """The five-minute test: no table building, no preprocessing."""
        a = [{"id": "1", "name": "Canon Deluxe Black Digital Camera Case - 2595B002"}]
        b = [{"id": "1", "name": "Canon PSC-85 Soft Camera Case - 2595B002"}]
        res = crosswalk(a, b, entity="product_electronics", id_field="id")
        assert [e["decision"] for e in res["matches"]] == ["match"]

    def test_a_capacity_difference_refutes(self):
        a = [{"id": "1", "name": "SanDisk Sansa Clip 16GB MP3 Player SDMX18"}]
        b = [{"id": "1", "name": "SanDisk Sansa Clip 32GB MP3 Player SDMX18"}]
        res = crosswalk(a, b, entity="product_electronics", id_field="id")
        assert "match" not in [e["decision"] for e in res["matches"]]
