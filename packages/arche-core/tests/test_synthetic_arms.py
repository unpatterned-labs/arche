# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The Splink arm (B9 S4) and the ledger arms (B9 S5).

These guard configuration fairness rather than arithmetic. A competitor arm
that is badly set up is worse than no competitor: it makes whatever it is
compared against look good for a reason that has nothing to do with the
comparison, and the first version of the Splink arm did exactly that -- it
scored 0.000 on relocated suppliers because `block_on` is case-sensitive and
57% of this world's representation differences are a source that stores IN
CAPITALS.

So: Splink is given normalised input, cut at its own decision boundary rather
than at a threshold borrowed from a different benchmark, and seeded. The
ledger arms are checked for the thing that would silently invalidate them --
that our record ids survive the round trip through arche's own record store.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SYNTHETIC = REPO / "data" / "synthetic"

# `arche_synthetic` writes Parquet, and pyarrow is an arche *extra*
# (`arche-core[parquet]`), not a base dependency. Without this the whole
# module ERRORS in a checkout that has not installed it, rather than
# skipping -- which is what happened in CI.
pytest.importorskip("pyarrow")

pytestmark = pytest.mark.skipif(
    not (SYNTHETIC / "arm_splink.py").exists(),
    reason="data/synthetic is not present in this checkout",
)

TINY = {"organisations": 25, "people": 40, "places": 20}


@pytest.fixture(scope="module")
def modules():
    if str(SYNTHETIC) not in sys.path:
        sys.path.insert(0, str(SYNTHETIC))
    import arche_synthetic
    import arms
    from arche_synthetic import evaluate

    return arche_synthetic, evaluate, arms


@pytest.fixture(scope="module")
def bench(modules, tmp_path_factory):
    synthetic, evaluate, _ = modules
    out = tmp_path_factory.mktemp("world")
    synthetic.build("ng_supplier_v0", seed=5, scale=TINY, out=out)
    return evaluate.Benchmark.load(out)


class TestTheSplinkArmIsConfiguredFairly:
    def test_input_is_normalised_before_it_reaches_splink(self, bench):
        """`block_on` is case-sensitive; unnormalised input broke every key."""
        pytest.importorskip("splink")
        from arm_splink import _frame

        frame = _frame(bench.observations)
        for column in ("name", "city", "address"):
            # `if v` is not enough: pandas types an all-null column as float64
            # and NaN is truthy, so filter on the type instead. A column that
            # HAS degenerated to float would also be a real problem for Splink,
            # which is why the name column is checked for it below.
            values = [v for v in frame[column].tolist() if isinstance(v, str)]
            assert values, column
            assert all(v == v.lower() for v in values), column
        assert all(v.isdigit() for v in frame["phone"].tolist() if isinstance(v, str))
        import pandas as pd
        assert not pd.api.types.is_numeric_dtype(frame["name"]), (
            "the name column degenerated to a numeric dtype; every comparison "
            "and every blocking key would silently misbehave")

    def test_a_blocking_key_survives_a_changed_city(self, bench):
        """A supplier that moved must still be retrievable, or the arm measures
        its own blocking and reports the result as recall."""
        pytest.importorskip("splink")
        from arm_splink import _frame

        frame = _frame(bench.observations)
        assert "name_head" in frame.columns
        heads = [v for v in frame["name_head"].tolist() if v]
        assert heads and all(len(v) <= 4 for v in heads)

    def test_the_threshold_is_splinks_own_decision_boundary(self):
        """0.99 was borrowed from a different benchmark and cost 0.52 recall.

        Imposing an arche-flavoured caution on an engine that has no third
        answer is the same error as scoring arche on a probability cut.
        """
        pytest.importorskip("splink")
        import arm_splink

        assert arm_splink.DEFAULT_THRESHOLD == 0.5

    def test_the_u_estimation_is_seeded(self):
        """Unseeded sampling moved an earlier arche benchmark by 0.03 recall
        between two runs in one session."""
        pytest.importorskip("splink")
        import inspect

        import arm_splink

        assert arm_splink.DEFAULT_SEED is not None
        assert "seed=seed" in inspect.getsource(arm_splink._train)


class TestTheLedgerArms:
    def test_our_record_ids_survive_the_round_trip(self, bench):
        """arche drops the `id_field`, so the ids come back through a
        passthrough attribute. If that broke, every cluster would be empty and
        the arm would silently score zero."""
        pytest.importorskip("duckdb")
        from arm_ledger import PASSTHROUGH, _record

        record = _record(bench.observations[0])
        assert record[PASSTHROUGH] == bench.observations[0]["record_id"]
        assert record["id"] == bench.observations[0]["record_id"]

    def test_the_passthrough_is_not_a_field_the_pack_compares(self):
        """It must be inert: a column arche scores would change the answer."""
        from arche.resolve import ENTITY_PACKS
        from arm_ledger import PASSTHROUGH

        assert PASSTHROUGH not in {c.get("field") for c in ENTITY_PACKS["organisation"]}

    def test_clusters_become_within_cluster_pairs(self, modules):
        from arm_ledger import _pairs

        assert _pairs([["a", "b", "c"], ["d"]]) == {("a", "b"), ("a", "c"), ("b", "c")}

    def test_ingestion_is_in_arrival_order(self):
        """The whole point of the arm: records arrive over years, and the
        supplier moves in between. Feeding them in id order would measure
        batch resolution with extra steps."""
        import inspect

        import arm_ledger

        source = inspect.getsource(arm_ledger.ledger_arm)
        assert 'key=lambda o: (o["observed_at"]' in source

    def test_the_observe_pass_looks_up_by_an_identifier_not_by_truth(self):
        """It may use the RC number, which is in the records. It may never use
        `truth_entity_id`, which is the answer."""
        import inspect

        import arm_ledger

        source = inspect.getsource(arm_ledger._observe_pass)
        assert "registration_id" in source
        assert "truth" not in source.replace("truth mapping", "").replace(
            "the truth", "")

    def test_the_ledger_arm_runs_end_to_end(self, bench, modules):
        pytest.importorskip("duckdb")
        from arm_ledger import ledger_arm

        predictions = ledger_arm(bench.observations)
        report = bench.score(predictions)
        assert report["overall"]["claimed_pairs"] >= 0
        assert predictions.clusters
        assert report["entities"]["clusters"] == len(predictions.clusters)
