# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The stratified evaluator (B9 S2) and the baseline arms (B9 S3).

The claims worth pinning are about *honesty*, not arithmetic:

* recall stratifies and precision does not, so no stratified precision is ever
  reported;
* blocking recall is never quietly filled in with the arm's own recall;
* an engine that can abstain is reported with a coverage figure beside its
  recall, so it is not scored as if it only had two answers;
* a perfect matcher scores 1.0 and a matcher that claims everything has low
  precision -- the ordinary sanity checks, on a tiny hand-built world.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SYNTHETIC = REPO / "data" / "synthetic"

pytestmark = pytest.mark.skipif(
    not (SYNTHETIC / "arche_synthetic" / "evaluate.py").exists(),
    reason="data/synthetic is not present in this checkout",
)

TINY = {"organisations": 40, "people": 60, "places": 30}


@pytest.fixture(scope="module")
def modules():
    if str(SYNTHETIC) not in sys.path:
        sys.path.insert(0, str(SYNTHETIC))
    if importlib.util.find_spec("arche_synthetic") is None:  # pragma: no cover
        pytest.skip("arche_synthetic not importable")
    import arche_synthetic
    import arms
    from arche_synthetic import evaluate

    return arche_synthetic, evaluate, arms


@pytest.fixture(scope="module")
def bench(modules, tmp_path_factory):
    synthetic, evaluate, _ = modules
    out = tmp_path_factory.mktemp("world")
    synthetic.build("ng_supplier_v0", seed=11, scale=TINY, out=out)
    return evaluate.Benchmark.load(out)


class TestTheTruthItLoads:
    def test_true_pairs_are_all_and_only_same_entity_pairs(self, bench):
        for a, b in bench.true_pairs:
            assert bench.truth[a] == bench.truth[b]
        expected = sum(len(m) * (len(m) - 1) // 2 for m in bench.by_entity.values())
        assert len(bench.true_pairs) == expected

    def test_pairs_are_unordered_keys(self, modules):
        _, evaluate, _ = modules
        assert evaluate.pair("b", "a") == evaluate.pair("a", "b") == ("a", "b")

    def test_strata_are_populated_and_are_subsets_of_the_true_pairs(self, bench):
        assert set(bench.by_kind) == {"change", "representation", "error"}
        for name, pairs in bench.by_kind.items():
            # Every difference is between two observations of ONE entity, so a
            # stratum can only ever be a subset of the true pairs. This is the
            # structural reason precision cannot be stratified.
            assert pairs <= bench.true_pairs, name
            assert pairs, name

    def test_strata_may_overlap(self, bench):
        """A pair whose address moved AND whose OCR mangled it is in both.

        The evaluator must never force a choice; that is why differences are
        one row per (pair, attribute, kind).
        """
        assert bench.by_kind["change"] & bench.by_kind["error"]


class TestScoringHonesty:
    def test_a_perfect_matcher_scores_one(self, bench, modules):
        _, evaluate, _ = modules
        report = bench.score(evaluate.Predictions(
            arm="oracle", pairs=set(bench.true_pairs),
            candidates=set(bench.true_pairs)))
        assert report["overall"]["precision"] == 1.0
        assert report["overall"]["recall"] == 1.0
        assert report["bcubed"]["f1"] == 1.0
        assert report["entities"]["false_merge_clusters"] == 0
        assert all(s["recall"] == 1.0 for s in report["recall_by_stratum"].values())

    def test_a_matcher_that_finds_nothing_scores_zero_everywhere(self, bench, modules):
        _, evaluate, _ = modules
        report = bench.score(evaluate.Predictions(arm="null", pairs=set()))
        assert report["overall"]["recall"] == 0.0
        assert all(s["recall"] == 0.0 for s in report["recall_by_stratum"].values())
        assert report["entities"]["false_merge_clusters"] == 0

    def test_no_stratified_precision_is_ever_reported(self, bench, modules):
        """The invariant the module exists to protect.

        A false merge joins two different entities, so it has no difference row
        and belongs to no stratum. A stratified precision column would have no
        denominator and would be an invented number that reads as authoritative.
        """
        _, evaluate, _ = modules
        report = bench.score(evaluate.Predictions(arm="x", pairs=set(bench.true_pairs)))
        for stratum in report["recall_by_stratum"].values():
            assert set(stratum) == {"true_pairs", "recall"}
            assert "precision" not in stratum and "f1" not in stratum

    def test_blocking_recall_is_never_the_arms_recall_in_disguise(self, bench, modules):
        """Falling back to the positive pairs would make the two identical by
        construction, and print a lie in the flattering direction."""
        _, evaluate, _ = modules
        report = bench.score(evaluate.Predictions(
            arm="no-candidates", pairs=set(list(bench.true_pairs)[:5])))
        assert report["blocking"]["measured"] is False
        assert "recall" not in report["blocking"]

    def test_a_reported_blocking_recall_says_it_was_reported(self, bench, modules):
        _, evaluate, _ = modules
        report = bench.score(evaluate.Predictions(
            arm="arche/x", pairs=set(),
            notes={"blocking_recall_reported_by_arche": 0.99, "candidate_pairs": 10}))
        assert report["blocking"]["recall"] == 0.99
        assert "reported by the arm" in report["blocking"]["source"]

    def test_an_engine_that_abstains_gets_a_coverage_figure(self, bench, modules):
        """Recall counts automatic merges; coverage counts merged-or-surfaced.

        Scoring an engine with three answers as if it had two understates every
        engine with a refusal mechanism.
        """
        _, evaluate, _ = modules
        half = sorted(bench.true_pairs)
        report = bench.score(evaluate.Predictions(
            arm="cautious", pairs=set(half[:10]), abstentions=set(half[10:])))
        assert report["overall"]["recall"] < report["overall"]["coverage"]
        assert report["overall"]["coverage"] == 1.0
        assert report["overall"]["abstentions"] == len(half) - 10

    def test_abstentions_are_never_scored_as_right_or_wrong(self, bench, modules):
        """An abstention folded into either answer would be decorative."""
        _, evaluate, _ = modules
        wrong = {("rec_ffffffffffffffff", "rec_eeeeeeeeeeeeeeee")}
        a = bench.score(evaluate.Predictions(arm="a", pairs=set()))
        b = bench.score(evaluate.Predictions(arm="b", pairs=set(), abstentions=wrong))
        assert a["overall"]["precision"] == b["overall"]["precision"]
        assert a["overall"]["recall"] == b["overall"]["recall"]

    def test_false_merges_are_explained_by_what_was_shared(self, bench, modules):
        """Where a stratified precision column would have gone."""
        _, evaluate, _ = modules
        entities = sorted(bench.by_entity)
        a = bench.by_entity[entities[0]][0]
        b = bench.by_entity[entities[1]][0]
        report = bench.score(evaluate.Predictions(
            arm="merger", pairs={evaluate.pair(a, b)}))
        assert report["overall"]["precision"] == 0.0
        assert report["false_merges_by_what_was_shared"]


class TestTheArms:
    def test_normalise_sets_aside_the_legal_form(self, modules):
        _, _, arms = modules
        assert (arms.normalise("Okafor Engineering Limited")
                == arms.normalise("OKAFOR ENGINEERING LTD.")
                == "okafor engineering")

    def test_normalise_never_empties_a_name_that_is_all_form_words(self, modules):
        """Stripping every token would make unrelated companies join."""
        _, _, arms = modules
        assert arms.normalise("Nigeria Limited")

    def test_the_exact_arm_claims_only_identical_normalised_names(self, bench, modules):
        _, _, arms = modules
        predictions = arms.exact(bench.observations)
        by_id = {o["record_id"]: o for o in bench.observations}
        for a, b in predictions.pairs:
            assert arms.normalise(by_id[a]["name"]) == arms.normalise(by_id[b]["name"])
            assert (by_id[a]["city"] or "").upper() == (by_id[b]["city"] or "").upper()

    def test_the_exact_arm_is_worse_on_legitimate_change_than_overall(self, bench, modules):
        """**The headline of the benchmark.**

        A rule join looks respectable overall and collapses where the entity
        moved: a relocated supplier has a different city, so the join key is
        gone. This is the row that makes the argument, and it is asserted here
        so that a generator change which quietly stops producing meaningful
        change fails a test instead of producing a flattering table.
        """
        _, evaluate, arms = modules
        report = bench.score(arms.exact(bench.observations))
        overall = report["overall"]["recall"]
        relocated = report["recall_by_stratum"].get("change/ORG_RELOCATED")
        assert relocated, "no relocation pairs in this world"
        assert relocated["recall"] < overall, (
            f"the exact join scored {relocated['recall']} on relocations against "
            f"{overall} overall -- if a rule baseline handles legitimate change "
            "as well as anything else, the changes being generated are too "
            "small to measure anything")

    def test_the_arms_report_their_own_candidates(self, bench, modules):
        _, _, arms = modules
        for arm in (arms.exact, arms.jaro_winkler):
            predictions = arm(bench.observations)
            assert predictions.candidates >= predictions.pairs
            assert predictions.seconds >= 0

    def test_the_custom_comparators_read_what_the_pack_ignores(self, modules):
        """The shipped `organisation` pack declares `ignores_everything_else`
        and reads none of phone, TIN, account or director -- where a third of
        the labelled changes live."""
        _, _, arms = modules
        fields = {c.get("field") for c in arms._custom_comparators()}
        assert {"tin", "account_number", "phone", "director_name"} <= fields
        from arche.resolve import ENTITY_PACKS
        assert not {"tin", "account_number", "phone", "director_name"} & {
            c.get("field") for c in ENTITY_PACKS["organisation"]}
