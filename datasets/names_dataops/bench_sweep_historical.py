# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Splink and arche on `historical_50k`, compared at matched precision.

The earlier run compared one operating point each: Splink at a 0.99 match
probability, arche at its defaults. That measures the two default settings, not
the two engines. This sweeps both and reads recall off at the same precision, so
the comparison is like for like.

It also answers a question the single-point run could not: **how much of the gap
is scoring, and how much is candidate generation.** A matcher can only decide
pairs it was shown. If a true pair never becomes a candidate, no threshold
recovers it, and the ceiling that imposes is reported here first, because it
bounds everything else.

Both engines are asked for everything they will emit:

* Splink predicts at a 0.01 match probability, so its curve runs almost the
  whole way down.
* arche runs with `threshold=0.0, review_margin=0.0`, which stops the engine
  discarding candidates before they are scored. Its curve is then swept over
  the emitted edge scores.

That second setting is not a mode anybody should run in production. It exists
here to separate "arche scored this pair badly" from "arche never saw it".
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_HERE))

from bench_splink_historical import SAME_FIELDS, norm, truth_pairs  # noqa: E402

OUT = _HERE / "bench_sweep_historical_result.json"
# Precisions to read recall off at. 0.99 is roughly where an auto-merge belongs.
MATCH_AT = (0.999, 0.99, 0.98, 0.95, 0.90)


def dedupe_scored(scored: list[tuple[tuple[str, str], float]]
                  ) -> list[tuple[tuple[str, str], float]]:
    """One entry per pair, keeping its best score.

    A dedupe run self-links, so arche emits every pair twice, once from each
    side. Left in, the curve counts each hit twice and reports a recall above
    the blocking ceiling, which is how this was caught.
    """
    best: dict[tuple[str, str], float] = {}
    for pair, score in scored:
        if pair not in best or score > best[pair]:
            best[pair] = score
    return list(best.items())


def curve(scored: list[tuple[tuple[str, str], float]],
          truth: set[tuple[str, str]]) -> list[dict]:
    """Precision and recall at every distinct score, best score first."""
    scored = sorted(dedupe_scored(scored), key=lambda x: -x[1])
    n_true = len(truth)
    hit = seen = 0
    out, last = [], None
    for pair, score in scored:
        seen += 1
        if pair in truth:
            hit += 1
        if score != last:
            out.append({"threshold": round(float(score), 4),
                        "predicted": seen,
                        "precision": hit / seen,
                        "recall": hit / n_true})
            last = score
    if out and out[-1]["predicted"] != seen:
        out.append({"threshold": round(float(scored[-1][1]), 4),
                    "predicted": seen, "precision": hit / seen,
                    "recall": hit / n_true})
    return out


def recall_at_precision(points: list[dict], target: float) -> dict | None:
    """The most recall available while holding precision at or above target."""
    best = None
    for p in points:
        if p["precision"] >= target and (best is None or p["recall"] > best["recall"]):
            best = p
    return best


def run_splink(df):
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    settings = SettingsCreator(
        link_type="dedupe_only",
        blocking_rules_to_generate_predictions=[
            block_on("substr(first_name,1,3)", "substr(surname,1,4)"),
            block_on("surname", "dob"),
            block_on("first_name", "dob"),
            block_on("postcode_fake", "first_name"),
            block_on("postcode_fake", "surname"),
            block_on("dob", "birth_place"),
            block_on("substr(postcode_fake,1,3)", "dob"),
            block_on("substr(postcode_fake,1,3)", "first_name"),
            block_on("substr(postcode_fake,1,3)", "surname"),
            block_on("substr(first_name,1,2)", "substr(surname,1,2)",
                     "substr(dob,1,4)"),
        ],
        comparisons=[
            cl.NameComparison("first_name").configure(term_frequency_adjustments=True),
            cl.NameComparison("surname").configure(term_frequency_adjustments=True),
            cl.DateOfBirthComparison("dob", input_is_string=True),
            cl.ExactMatch("postcode_fake").configure(term_frequency_adjustments=True),
            cl.ExactMatch("birth_place").configure(term_frequency_adjustments=True),
            cl.ExactMatch("occupation").configure(term_frequency_adjustments=True),
        ],
        retain_intermediate_calculation_columns=False,
    )
    linker = Linker(df, settings, db_api=DuckDBAPI())
    linker.training.estimate_probability_two_random_records_match(
        [block_on("first_name", "surname", "dob")], recall=0.6)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6)
    for rule in (block_on("first_name", "surname"), block_on("dob")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)

    out = linker.inference.predict(
        threshold_match_probability=0.01).as_pandas_dataframe()
    return [(norm(p), s) for p, s in zip(
        zip(out["unique_id_l"], out["unique_id_r"], strict=False),
        out["match_probability"], strict=False)]


def run_arche(df, comparators):
    from arche.resolve.reconcile import reconcile

    recs = [{"id": r.unique_id, "name": r.first_and_surname or "",
             "birth_date": r.dob or "", "postcode": r.postcode_fake or "",
             "birth_place": r.birth_place or "", "occupation": r.occupation or ""}
            for r in df.itertuples()]
    # threshold=0 and review_margin=0 keep every scored candidate, so the curve
    # is limited by blocking rather than by the default decision point.
    res = reconcile(recs, recs, comparators=comparators, id_field="id",
                    threshold=0.0, review_margin=0.0, tf="default")
    return [(norm((e["a_id"], e["b_id"])), e["score"])
            for e in res["matches"] if e["a_id"] != e["b_id"]]


def main() -> int:
    warnings.filterwarnings("ignore")
    from splink.datasets import splink_datasets

    df = splink_datasets.historical_50k
    truth = truth_pairs(df)
    print(f"  historical_50k: {len(df):,} records, {len(truth):,} true pairs\n",
          flush=True)

    engines = {}
    print("  running splink ...", flush=True)
    engines["splink"] = run_splink(df)
    print("  running arche (same five fields) ...", flush=True)
    engines["arche"] = run_arche(df, SAME_FIELDS)

    report: dict[str, dict] = {}
    print(f"\n  {'engine':<10}{'candidates':>12}{'ceiling':>10}"
          "   (recall if every candidate were merged)")
    for name, scored in engines.items():
        pairs = {p for p, _ in scored}
        ceiling = len(pairs & truth) / len(truth)
        report[name] = {"candidates": len(pairs), "recall_ceiling": round(ceiling, 4)}
        print(f"  {name:<10}{len(pairs):>12,}{ceiling:>10.4f}")

    print(f"\n  recall at matched precision\n  {'precision':<12}"
          f"{'splink':>10}{'arche':>10}{'gap':>10}")
    for target in MATCH_AT:
        row = {}
        for name, scored in engines.items():
            pt = recall_at_precision(curve(scored, truth), target)
            row[name] = pt
            report[name].setdefault("at_precision", {})[str(target)] = (
                {"recall": round(pt["recall"], 4),
                 "threshold": pt["threshold"],
                 "predicted": pt["predicted"]} if pt else None)
        s = row["splink"]["recall"] if row["splink"] else 0.0
        a = row["arche"]["recall"] if row["arche"] else 0.0
        print(f"  {target:<12.3f}{s:>10.4f}{a:>10.4f}{a - s:>10.4f}")

    OUT.write_text(json.dumps({
        "benchmark": "historical_50k, precision-matched sweep",
        "records": len(df), "true_pairs": len(truth),
        "arche_settings": "threshold=0.0, review_margin=0.0 so blocking is the "
                          "only limit; not a production setting",
        "splink_settings": "predict at match_probability >= 0.01",
        "engines": report,
    }, indent=2), encoding="utf-8")
    print(f"\n  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
