# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Q1: does "Splink as the base scorer" hold for products? Splink on Abt-Buy.

    uv run python datasets/products_dataops/bench_splink_abt_buy.py

The question (plan §7f)
-----------------------
Splink is general-purpose Fellegi-Sunter: hand it sensible columns and it
scores products as readily as people. The proposal is to make it arche's
default scorer and keep arche as the layer that *declares* identity, guards
it, decides and remembers. This is the first product test of that proposal,
on the one labelled product benchmark arche gates in CI.

The recipe, and what arche supplies to it
-----------------------------------------
Abt-Buy has one usable shared column: the product name. Splink cannot compare
a model code it has not been given, so **arche's representation runs first**
-- `extract_product_code_candidates` pulls `pslx350h` out of `Sony Turntable
- PSLX350H`, `extract_specs` pulls `500gb` out of a hard drive -- and Splink
compares the columns that come out:

    code1        the first extracted code, exact match with term frequency
    codes        every extracted code, array-intersect level
    brand        first token of the name, exact match with term frequency
    name         the normalised title, Jaro-Winkler levels
    tokens       title tokens, array-intersect-at-sizes
    specs        `unit:value` strings; both present and DISJOINT is a level
                 of its own, so EM prices the refutation instead of us

Same input as arche's arm: names only, `tf=None`. Buy's `manufacturer` and
both sides' `description` are withheld so the comparison with the gated arche
number (741 true, 22 false, precision 0.9712) is on the same evidence.

The two invariants
------------------
arche's product pack carries two properties the gate enforces: on Abt-Buy the
spec refutation is neutral (the auto-match set is identical with and without
it) and the electronics stop list is inert. §7f asks whether such guarantees
survive *inside* a learned model or must stay outside it. So the recipe is run
three ways -- as written, without the spec comparison, with the stop list
emptied at extraction -- and the match sets are compared at the same
threshold, and the weight EM assigned to the "specs disjoint" level is
printed. A learned weight near zero is neutrality; a strongly negative one is
a refutation the model found for itself.

Thresholds
----------
Reported at 0.5, 0.9, 0.99 and at the best-F1 point. The best-F1 point is
chosen on the labels and says so. arche's arm has no threshold to tune.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
DATA = _REPO / "data" / "er_bench" / "products"
GATE = _REPO / "data" / "er_bench" / "benchmark_abt_buy_result.json"
OUT = Path(__file__).with_name("bench_splink_abt_buy_result.json")

THRESHOLDS = (0.5, 0.9, 0.99)
_WORD = re.compile(r"[a-z0-9]+")


def read(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").casefold()))


# --- arche's representation, as columns -----------------------------------------

def represent(rows: list[dict], *, stop_list: bool = True) -> list[dict]:
    """What arche extracts from a title, laid out as columns for Splink."""
    from arche.resolve._productcode import (
        PRODUCT_CATEGORIES, ProductCategory, extract_product_code_candidates,
        extract_specs, register_category)

    original = PRODUCT_CATEGORIES["electronics"]
    if not stop_list:
        register_category(ProductCategory(name="electronics",
                                          identity_units=original.identity_units,
                                          stop_codes=frozenset()), replace=True)
    try:
        out = []
        for r in rows:
            name = norm(r["name"])
            codes = sorted(extract_product_code_candidates(r["name"], category="electronics"))
            specs = sorted(f"{unit}:{v:g}" for unit, values in
                           extract_specs(r["name"], "electronics").items() for v in values)
            tokens = [t for t in name.split() if len(t) > 1]
            out.append({"unique_id": r["id"], "name": name,
                        "brand": tokens[0] if tokens else None,
                        "code1": codes[0] if codes else None,
                        "codes": codes, "tokens": tokens, "specs": specs})
        return out
    finally:
        if not stop_list:
            register_category(original, replace=True)


# --- the recipe ------------------------------------------------------------------

#: Two recipes, and the contrast between them is the finding. `descriptive`
#: is what a Splink user would write: every column arche extracted, plus the
#: title itself. `identity` keeps only the columns the pack declares
#: identity-bearing -- the code and the brand -- and withholds title
#: similarity from the model entirely.
RECIPES = ("descriptive", "identity")


def settings(recipe: str, *, with_spec: bool):
    import splink.comparison_level_library as cll
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    code = cl.CustomComparison(output_column_name="code", comparison_levels=[
        cll.NullLevel("code1"),
        cll.ExactMatchLevel("code1").configure(tf_adjustment_column="code1"),
        cll.ArrayIntersectLevel("codes", min_intersection=1),
        cll.ElseLevel(),
    ])
    spec = cl.CustomComparison(output_column_name="spec", comparison_levels=[
        cll.CustomLevel("len(specs_l) = 0 OR len(specs_r) = 0",
                        label_for_charts="a spec missing on one side"
                        ).configure(is_null_level=True),
        cll.ArrayIntersectLevel("specs", min_intersection=1),
        # Both sides carry a spec and they share none. This is the level
        # arche refutes on; here EM prices it.
        cll.ElseLevel(),
    ])
    comparisons = [code, cl.ExactMatch("brand").configure(term_frequency_adjustments=True)]
    if recipe == "descriptive":
        comparisons += [cl.JaroWinklerAtThresholds("name", [0.92, 0.85]),
                        cl.ArrayIntersectAtSizes("tokens", [4, 3, 2])]
    if with_spec:
        comparisons.append(spec)
    return SettingsCreator(
        link_type="link_only",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=[
            block_on("code1"),
            block_on("brand"),
            block_on("substr(name,1,10)"),
        ],
        retain_intermediate_calculation_columns=False,
    )


def run(a: list[dict], b: list[dict], recipe: str, *, with_spec: bool
        ) -> tuple[list[tuple[tuple[str, str], float]], dict[str, float]]:
    import pandas as pd
    from splink import DuckDBAPI, Linker, block_on

    linker = Linker([pd.DataFrame(a), pd.DataFrame(b)], settings(recipe, with_spec=with_spec),
                    db_api=DuckDBAPI(), input_table_aliases=["abt", "buy"])
    linker.training.estimate_probability_two_random_records_match(
        [block_on("code1")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=42)
    # Brand-blocked EM trains code, name, tokens and spec; code-blocked EM
    # trains brand. Never a rule on a column being trained (§7d's trap).
    for rule in (block_on("brand"), block_on("code1")):
        try:
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
        except Exception as exc:      # noqa: BLE001
            print(f"    EM on {rule} did not converge: {exc}", flush=True)

    learned: dict[str, float] = {}
    for c in linker.misc.save_model_to_json()["comparisons"]:
        for lv in c["comparison_levels"]:
            m, u = lv.get("m_probability"), lv.get("u_probability")
            if m and u:
                learned[f"{c['output_column_name']}: {lv['label_for_charts']}"] = round(
                    math.log2(m / u), 2)

    out = linker.inference.predict(threshold_match_probability=0.01).as_pandas_dataframe()
    got = []
    for left, right, p in zip(out["unique_id_l"], out["unique_id_r"],
                              out["match_probability"], strict=False):
        # link_only does not fix which frame lands in `_l`; Abt ids are short.
        left, right = str(left), str(right)
        abt, buy = (left, right) if len(left) < len(right) else (right, left)
        got.append(((abt, buy), float(p)))
    return got, learned


# --- main --------------------------------------------------------------------------

def score(pairs: set, truth: set) -> dict[str, Any]:
    tp, fp = len(pairs & truth), len(pairs - truth)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / len(truth)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"true": tp, "false": fp, "precision": round(prec, 4),
            "recall": round(rec, 4), "f1": round(f1, 4)}


def main() -> int:
    warnings.filterwarnings("ignore")
    abt_rows, buy_rows = read("Abt.csv"), read("Buy.csv")
    truth = {(r["idAbt"], r["idBuy"]) for r in read("abt_buy_perfectMapping.csv")}
    gate = json.loads(GATE.read_text(encoding="utf-8"))["configurations"]["product_electronics"]
    print(f"  Abt {len(abt_rows):,} x Buy {len(buy_rows):,}, {len(truth):,} true pairs")
    print(f"  arche gate: {gate['tp']} true, {gate['fp']} false, "
          f"precision {gate['precision']}, recall {gate['recall']}\n", flush=True)

    a, b = represent(abt_rows), represent(buy_rows)
    with_codes = sum(1 for r in a + b if r["code1"])
    with_specs = sum(1 for r in a + b if r["specs"])
    print(f"  representation: {with_codes:,} of {len(a) + len(b):,} records carry a code, "
          f"{with_specs:,} a spec\n", flush=True)

    report: dict[str, Any] = {"records": {"abt": len(a), "buy": len(b)},
                              "true_pairs": len(truth), "arche_gate": gate, "arms": {}}

    def sweep(got: list) -> tuple[float, dict]:
        best = (None, {"f1": -1.0})
        for t in (i / 100 for i in range(5, 100, 5)):
            r = score({p for p, s in got if s >= t}, truth)
            if r["f1"] > best[1]["f1"]:
                best = (t, r)
        return best

    for recipe in RECIPES:
        print(f"  splink, {recipe} recipe ...", flush=True)
        t0 = time.time()
        got, learned = run(a, b, recipe, with_spec=True)
        secs = time.time() - t0
        arms = {}
        for t in THRESHOLDS:
            arms[f"p>={t}"] = score({p for p, s in got if s >= t}, truth)
        best_t, best = sweep(got)
        arms[f"best-F1 (p>={best_t:.2f}, chosen on labels)"] = best

        # --- invariants inside the model ---------------------------------
        at = {p for p, s in got if s >= best_t}
        got_nospec, _ = run(a, b, recipe, with_spec=False)
        nospec = {p for p, s in got_nospec if s >= best_t}
        a2, b2 = represent(abt_rows, stop_list=False), represent(buy_rows, stop_list=False)
        got_nostop, _ = run(a2, b2, recipe, with_spec=True)
        nostop = {p for p, s in got_nostop if s >= best_t}
        report["arms"][recipe] = {
            "results": arms, "learned_bits": learned, "seconds": round(secs, 1),
            "invariants": {
                "threshold": best_t,
                "spec_refutation_neutral": at == nospec,
                "spec_delta": {"only_with_spec": len(at - nospec),
                               "only_without": len(nospec - at),
                               "without_spec": score(nospec, truth)},
                "stop_list_inert": at == nostop,
                "stop_delta": {"only_with_stop": len(at - nostop),
                               "only_without": len(nostop - at),
                               "without_stop_list": score(nostop, truth)},
            },
        }

    # --- print -------------------------------------------------------------
    g = gate
    print(f"\n  {'arm':<52}{'prec':>7}{'recall':>8}{'F1':>7}{'true':>6}{'false':>7}")
    print(f"  {'arche product_electronics (gated, no threshold)':<52}{g['precision']:>7.3f}"
          f"{g['recall']:>8.3f}{2*g['precision']*g['recall']/(g['precision']+g['recall']):>7.3f}"
          f"{g['tp']:>6}{g['fp']:>7}")
    for recipe, block in report["arms"].items():
        for label, r in block["results"].items():
            print(f"  {'splink ' + recipe + ' ' + label:<52}{r['precision']:>7.3f}"
                  f"{r['recall']:>8.3f}{r['f1']:>7.3f}{r['true']:>6}{r['false']:>7}")
    for recipe, block in report["arms"].items():
        print(f"\n  {recipe}: learned weights (bits)")
        for k, v in block["learned_bits"].items():
            print(f"    {k:<58}{v:>+7.2f}")
        inv = block["invariants"]
        print(f"  {recipe}: invariants at p>={inv['threshold']:.2f}")
        print(f"    spec refutation neutral : {inv['spec_refutation_neutral']}  "
              f"(+{inv['spec_delta']['only_with_spec']} / -{inv['spec_delta']['only_without']} pairs; "
              f"without spec: {inv['spec_delta']['without_spec']['true']} true, "
              f"{inv['spec_delta']['without_spec']['false']} false)")
        print(f"    stop list inert         : {inv['stop_list_inert']}  "
              f"(+{inv['stop_delta']['only_with_stop']} / -{inv['stop_delta']['only_without']} pairs)")

    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\n  wrote {OUT.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
