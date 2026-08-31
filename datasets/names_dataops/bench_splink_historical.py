# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Splink's `historical_50k` deduplication, with arche run beside it.

The companion to `bench_splink_febrl.py`, on the dataset that is *not* synthetic
in the same way. Febrl's records were invented by a generator and then corrupted
by it. `historical_50k` is 50,578 records describing 5,156 real UK historical
figures, taken from Wikidata, with errors introduced afterwards. The names,
places and occupations are real and distributed the way real ones are, which is
the part a generator cannot fake and the part arche's whole thesis is about.

Why not ONS
-----------
ONS uses Splink in production, on the 2021 Census, the Business Index and the
Demographic Index. None of that data is public and no accuracy figures on it are
published, so there is nothing there to reproduce. This is the closest public
substitute: UK, real names, a published Splink recipe.

Splink publishes no accuracy number here either
-----------------------------------------------
Its `deduplicate_50k_synthetic` example shows charts, not figures. So unlike the
Febrl run there is no number to reproduce first, and what is reproduced instead
is the *recipe*: the ten blocking rules and five comparisons from that page. The
precision and recall below are computed here, identically for both engines,
against the `cluster` column both are blind to.

Two arche arms, for the same reason as the Febrl run
----------------------------------------------------
Splink is given name, date of birth, postcode, birth place and occupation. The
shipped `person` pack has comparators for the first two and nothing for the last
three, so running only the pack would compare a five-field model against a
two-field one and call the difference an engine gap.

* **shipped pack** is what somebody gets with `entity="person"` and no thought.
* **same fields** hands arche the same five columns through `comparators=`.

Deduplication, not linkage
--------------------------
One table. arche has no dedupe entry point, so it self-links and identity pairs
are dropped. Both engines are scored on *pairs*, not clusters: a cluster count
depends on the transitive closure each tool applies afterwards, and comparing
those would measure the closure rather than the matcher.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from itertools import combinations
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

OUT = _HERE / "bench_splink_historical_result.json"

# arche's person pack sees name and date of birth. This hands it the same five
# columns Splink gets. `category` is the closed-vocabulary comparator: it
# discriminates without confirming, which is what a birth place or an occupation
# does.
SAME_FIELDS = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
    {"field": "birth_date", "kind": "date", "weight": 2.0},
    {"field": "postcode", "kind": "postcode", "weight": 1.5},
    {"field": "birth_place", "kind": "category", "weight": 1.0},
    {"field": "occupation", "kind": "category", "weight": 0.5},
]


def truth_pairs(df) -> set[tuple[str, str]]:
    """Every within-cluster pair. The `cluster` column is a Wikidata entity id."""
    by_cluster: dict[str, list[str]] = {}
    for uid, cid in zip(df["unique_id"], df["cluster"], strict=False):
        by_cluster.setdefault(cid, []).append(uid)
    out = set()
    for ids in by_cluster.values():
        for a, b in combinations(sorted(ids), 2):
            out.add((a, b))
    return out


def score(predicted: set[tuple[str, str]], truth: set[tuple[str, str]],
          label: str, extra=None) -> dict:
    hit = len(predicted & truth)
    prec = hit / len(predicted) if predicted else 0.0
    rec = hit / len(truth) if truth else 0.0
    out = {"engine": label, "predicted_pairs": len(predicted),
           "true_pairs_found": hit, "false_pairs": len(predicted) - hit,
           "precision": round(prec, 4), "recall": round(rec, 4),
           "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}
    out.update(extra or {})
    return out


def norm(pair) -> tuple[str, str]:
    a, b = pair
    return (a, b) if a <= b else (b, a)


# ---------------------------------------------------------------- splink ----
def run_splink(df) -> tuple[set, dict]:
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    # The ten blocking rules from Splink's published example.
    blocking = [
        block_on("substr(first_name,1,3)", "substr(surname,1,4)"),
        block_on("surname", "dob"),
        block_on("first_name", "dob"),
        block_on("postcode_fake", "first_name"),
        block_on("postcode_fake", "surname"),
        block_on("dob", "birth_place"),
        block_on("substr(postcode_fake,1,3)", "dob"),
        block_on("substr(postcode_fake,1,3)", "first_name"),
        block_on("substr(postcode_fake,1,3)", "surname"),
        block_on("substr(first_name,1,2)", "substr(surname,1,2)", "substr(dob,1,4)"),
    ]
    settings = SettingsCreator(
        link_type="dedupe_only",
        blocking_rules_to_generate_predictions=blocking,
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

    res = linker.inference.predict(threshold_match_probability=0.5)
    out = res.as_pandas_dataframe()
    at99 = out[out["match_probability"] >= 0.99]
    pairs = {norm(p) for p in zip(at99["unique_id_l"], at99["unique_id_r"],
                                  strict=False)}
    return pairs, {"edges_above_0.5": len(out), "threshold": 0.99}


# ----------------------------------------------------------------- arche ----
def run_arche(df, comparators=None) -> set:
    from arche.resolve import reconcile

    recs = [{"id": r.unique_id,
             "name": r.first_and_surname or "",
             "birth_date": r.dob or "",
             "postcode": r.postcode_fake or "",
             "birth_place": r.birth_place or "",
             "occupation": r.occupation or ""}
            for r in df.itertuples()]
    kw = {"comparators": comparators} if comparators else {"entity": "person"}
    res = reconcile(recs, recs, id_field="id", **kw)
    return {norm((e["a_id"], e["b_id"])) for e in res["matches"]
            if e["decision"] == "match" and e["a_id"] != e["b_id"]}


def main() -> int:
    warnings.filterwarnings("ignore")
    from splink.datasets import splink_datasets

    df = splink_datasets.historical_50k
    truth = truth_pairs(df)
    print(f"  historical_50k: {len(df):,} records, {df['cluster'].nunique():,} "
          f"entities, {len(truth):,} true pairs\n", flush=True)

    results = []
    t0 = time.time()
    sp_pairs, sp_meta = run_splink(df)
    sp_meta["seconds"] = round(time.time() - t0, 1)
    r = score(sp_pairs, truth, "splink (its own recipe)", sp_meta)
    results.append(r)
    print(f"  {r['engine']:<28} pairs {r['predicted_pairs']:>7}  "
          f"precision {r['precision']:.4f}  recall {r['recall']:.4f}  "
          f"F1 {r['f1']:.4f}  ({sp_meta['seconds']}s)", flush=True)

    for label, comps in (("arche (shipped person pack)", None),
                         ("arche (same five fields)", SAME_FIELDS)):
        t0 = time.time()
        pairs = run_arche(df, comps)
        r = score(pairs, truth, label, {"seconds": round(time.time() - t0, 1)})
        results.append(r)
        print(f"  {label:<28} pairs {r['predicted_pairs']:>7}  "
              f"precision {r['precision']:.4f}  recall {r['recall']:.4f}  "
              f"F1 {r['f1']:.4f}  ({r['seconds']}s)", flush=True)

    OUT.write_text(json.dumps({
        "benchmark": "splink historical_50k deduplication, arche beside it",
        "why_not_ons": ("ONS runs Splink on the 2021 Census, the Business Index "
                        "and the Demographic Index, none of it public and no "
                        "accuracy published, so there is nothing to reproduce"),
        "splink_publishes_no_accuracy_here": (
            "its deduplicate_50k_synthetic example shows charts only; the recipe "
            "is reproduced, the numbers are computed here for both engines"),
        "scored_on": "pairs, not clusters, so transitive closure is not measured",
        "records": len(df), "entities": int(df["cluster"].nunique()),
        "true_pairs": len(truth),
        "splink_version": __import__("splink").__version__,
        "arms": results,
    }, indent=2), encoding="utf-8")
    print(f"\n  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
