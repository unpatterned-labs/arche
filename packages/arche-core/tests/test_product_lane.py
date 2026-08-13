# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for the experimental electronics product lane.

The measurement this lane is built on, from Leipzig Abt-Buy (complete ground
truth): with the rules that ship, code-blocking reaches 0.8865 precision over
881 pairs and the rarity filter lifts it to 0.9499 over 818.

Two mechanisms produce that, and the split matters. With `stop_codes` disabled,
code-blocking is 0.5570 and there is a bucket of 503 pairs sharing a code seen
20+ times containing no true match at all; the stop list removes it at zero
recall cost. With the list on, the maximum document frequency is 11, so that
bucket does not exist. The short blocklist does more work than the frequency
table — what the table earns is the separation inside what remains.
"""

from __future__ import annotations

import copy

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

    def test_bare_in_is_not_a_unit(self):
        """`in` is excluded because it fires inside `3-in-1`.

        Reading a charger's form factor as 3 inches made `3-in-1` and `5-in-1`
        disagree on a unit neither title mentions. `inch` carries it instead.
        """
        assert extract_specs("27 inch monitor")["inch"] == {27.0}
        assert extract_specs("Belkin 3-in-1 Charger") == {}

    def test_a_spec_is_never_carved_out_of_a_model_code(self):
        """The left-boundary bug: `F5C400300W` read as 400,300 watts.

        27.4% of identity-unit matches on Abt-Buy were fabricated this way, and
        it refuted a true pair — `F5C400300W` against `F5C400-300W`, the same
        product — for a 400,300W-vs-300W disagreement.
        """
        assert extract_specs("Belkin AC Anywhere - F5C400300W") == {}
        assert extract_specs("Netgear WNR3500L Router") == {}
        assert compare_specs("Belkin F5C400300W", "Belkin F5C400-300W") is None

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
        # Curve measured without `stop_codes`; the shape is what matters.
        assert code_rarity("ab0001x", tf) == 1.0
        assert code_rarity("16gb", tf) < 0.15

    def test_an_unseen_code_is_maximally_rare(self, tf):
        assert code_rarity("zz9999q", tf) == 1.0

    def test_common_codes_score_near_zero(self, tf):
        assert code_rarity("16gb", tf) < code_rarity("ab0001x", tf)


class TestCompareCodes:
    @pytest.fixture
    def tf(self):
        # A vocabulary, not two codes: `code_baseline_df` is estimated from
        # the corpus's own frequency distribution, so a degenerate two-code
        # table cannot say what "typical" means.
        return build_code_table(
            [f"Widget model AB{i:04d}X" for i in range(200)]
            + ["Cam 2595B002", "Case 2595B002"]
            + ["Thing 16GB"] * 20
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

    def test_a_common_shared_code_scores_below_the_gate_floor(self, tf):
        """What matters is that it cannot clear the gate on its own."""
        from arche.resolve._gate import DISTINCTIVE_FLOOR
        common = compare_codes("Player 16GB", "Recorder 16GB", tf)
        rare = compare_codes("Canon Case 2595B002", "Canon 2595B002 Cam", tf)
        assert common < DISTINCTIVE_FLOOR < rare

    def test_without_a_table_it_refuses(self, tf):
        """Fail loud, like `tftoken` does in the same situation.

        Returning 1.0 without a table makes a common code indistinguishable
        from a rare one, which drops block precision from 0.9499 to 0.8865 —
        a silently worse answer, which is the failure mode worth refusing.
        """
        with pytest.raises(ValueError, match="requires a frequency table"):
            compare_codes("Player 16GB", "Recorder 16GB", None)

    def test_a_table_without_counts_does_not_silently_pass(self, tf):
        """A `rel_freq`-only table has no document frequencies to read.

        Reading `_counts` directly returned `None` here and made *every* code
        score 1.0 — maximally rare, with no error. `_as_counts()` is the
        accessor that reconstructs them.
        """
        from arche.resolve._tokenfreq import TokenFrequencyTable

        bare = TokenFrequencyTable(rel_freq={"2595b002": 0.001})
        assert compare_codes("Canon 2595B002", "Case 2595B002", bare) is not None


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

    def test_re_registering_a_name_raises_unless_replace(self):
        """Silent overwrite is a process-wide change to how titles are read.

        Re-registering `electronics` with a longer minimum code length makes
        extraction return nothing, everywhere, with no error.
        """
        shadow = ProductCategory(name="electronics", min_code_len=99)
        with pytest.raises(ValueError, match="already registered"):
            register_category(shadow)
        assert extract_product_code_candidates("Sony HDRCX150", "electronics")

    def test_each_code_comparator_uses_its_own_category(self):
        """Two categories in one run must not share a table built for one.

        A table accumulated under one category's rules cannot answer questions
        about another's — the same class of bug as a phrase table built under a
        different tokenisation rule.
        """
        register_category(ProductCategory(
            name="_test_short", min_code_len=3, min_bare_number_len=3,
        ))
        try:
            a = [{"id": "1", "name": "Widget 501 model AB0001X"}]
            b = [{"id": "1", "name": "Widget 501 model AB0001X"}]
            res = crosswalk(a, b, id_field="id", comparators=[
                {"field": "name", "kind": "name", "weight": 1.0},
                {"field": "name", "kind": "code", "weight": 2.0,
                 "category": "electronics"},
                {"field": "name", "kind": "code", "weight": 2.0,
                 "category": "_test_short"},
            ])
            pins = res["pins"]["code_tf"]
            assert set(pins) == {"electronics", "_test_short"}
            assert pins["electronics"] != pins["_test_short"]
        finally:
            PRODUCT_CATEGORIES.pop("_test_short", None)


class TestReproducibility:
    def test_the_code_table_is_named_in_the_pins(self):
        """A scoring input that changes a decision must be in the pin.

        Two runs with different code tables can reach different verdicts on the
        same pair, so `decision_id` claims a reproducibility it does not have
        unless the table is pinned — the discipline the place pack follows with
        `shipped:place@sha256:...`.
        """
        a = [{"id": "1", "name": "Canon Case 2595B002"}]
        b = [{"id": "1", "name": "Canon 2595B002 Cam"}]
        res = crosswalk(a, b, entity="product_electronics", id_field="id")
        pin = res["pins"]["code_tf"]["electronics"]
        assert pin.startswith("codes@sha256:")

    def test_a_different_corpus_changes_the_pin(self):
        a = [{"id": "1", "name": "Canon Case 2595B002"}]
        b = [{"id": "1", "name": "Canon 2595B002 Cam"}]
        small = crosswalk(a, b, entity="product_electronics", id_field="id")
        big = crosswalk(
            a + [{"id": str(i), "name": f"Other AB{i:04d}X"} for i in range(2, 40)],
            b, entity="product_electronics", id_field="id",
        )
        assert (small["pins"]["code_tf"]["electronics"]
                != big["pins"]["code_tf"]["electronics"])


class TestBenchmarkContract:
    """Claims about the benchmark, enforced against the benchmark.

    The CHANGELOG asserted that a test pinned the `spec` refutation's
    neutrality. No such test existed — a claim about evidence, with no evidence
    behind it, in a release that exists to be measured. This is that test.
    """

    @pytest.fixture(scope="class")
    def abtbuy(self):
        import csv
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "data" / "er_bench" / "products"
        if not (root / "Abt.csv").exists():
            pytest.skip("Leipzig Abt-Buy not present")

        def read(name):
            with open(root / name, encoding="utf-8-sig", errors="replace",
                      newline="") as fh:
                return list(csv.DictReader(fh))

        return (
            [{"id": r["id"], "name": r["name"]} for r in read("Abt.csv")],
            [{"id": r["id"], "name": r["name"]} for r in read("Buy.csv")],
            {(r["idAbt"], r["idBuy"]) for r in read("abt_buy_perfectMapping.csv")},
        )

    @staticmethod
    def _auto(a, b, comparators):
        res = crosswalk(a, b, comparators=comparators, tf=None, id_field="id")
        return {(e["a_id"], e["b_id"]) for e in res["matches"]
                if e["decision"] == "match"}

    def test_the_spec_refutation_is_neutral_on_the_benchmark(self, abtbuy):
        """It must not start costing matches without someone noticing.

        Measured: the auto-match sets with and without `refutes_below` are
        identical. It earns its place from the SKU identity contract, not from
        this corpus — but if a future change makes it *harmful*, that is a
        different situation and this test is what surfaces it.
        """
        a, b, _ = abtbuy
        with_ref = ENTITY_PACKS["product_electronics"]
        without = [{k: v for k, v in s.items() if k != "refutes_below"}
                   for s in copy.deepcopy(with_ref)]
        assert self._auto(a, b, with_ref) == self._auto(a, b, without)

    def test_the_published_abt_buy_figures_hold(self, abtbuy):
        """P=0.9707, R=0.6636, TP 728, FP 22 — the numbers in the CHANGELOG."""
        a, b, truth = abtbuy
        auto = self._auto(a, b, ENTITY_PACKS["product_electronics"])
        tp = len(auto & truth)
        fp = len(auto - truth)
        assert (tp, fp) == (728, 22)
        assert round(tp / (tp + fp), 4) == 0.9707
        assert round(tp / len(truth), 4) == 0.6636

    def test_the_stop_list_is_inert_on_the_benchmark(self, abtbuy):
        """The claim that the table, not the stop list, does the work.

        Two earlier drafts got this attribution wrong in opposite directions.
        The stop list earns its place on catalogues too small to estimate
        frequency from, not on this one.
        """
        a, b, _ = abtbuy
        original = PRODUCT_CATEGORIES["electronics"]
        register_category(
            ProductCategory(name="electronics",
                            identity_units=original.identity_units,
                            stop_codes=frozenset()),
            replace=True,
        )
        try:
            without_list = self._auto(a, b, ENTITY_PACKS["product_electronics"])
        finally:
            register_category(original, replace=True)
        assert without_list == self._auto(a, b, ENTITY_PACKS["product_electronics"])

    def test_the_stop_list_earns_its_place_on_a_small_catalogue(self):
        """Where the table cannot help: every code looks rare in four records."""
        a = [{"id": "1", "name": "Sony TV 1080p"}, {"id": "2", "name": "LG TV 1080p"}]
        b = [{"id": "1", "name": "Philips TV 1080p"},
             {"id": "2", "name": "Toshiba TV 1080p"}]
        original = PRODUCT_CATEGORIES["electronics"]
        register_category(
            ProductCategory(name="electronics",
                            identity_units=original.identity_units,
                            stop_codes=frozenset()),
            replace=True,
        )
        try:
            merged = self._auto(a, b, ENTITY_PACKS["product_electronics"])
        finally:
            register_category(original, replace=True)
        assert merged, "without the stop list a shared resolution merges records"
        assert not self._auto(a, b, ENTITY_PACKS["product_electronics"])


class TestApplicabilityBound:
    def test_a_redundant_catalogue_warns(self):
        """The lane was measured where a code appears once per source.

        The baseline adapts, but it is estimated — a catalogue well outside the
        measured shape should say so rather than quietly report accuracy that
        was never established for it.
        """
        titles = [f"Widget AB{i:04d}X" for i in range(100)] * 6
        with pytest.warns(UserWarning, match="more redundancy than"):
            build_code_table(titles)

    def test_an_ordinary_catalogue_is_silent(self):
        import warnings as _w

        with _w.catch_warnings():
            _w.simplefilter("error")
            build_code_table([f"Widget AB{i:04d}X" for i in range(100)] * 2)


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
