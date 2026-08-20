# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Splink's own Febrl 4 recipe, reproduced, then arche beside it on the same task.

Every benchmark arche publishes is one arche chose. The cure is to take someone
else's, reproduce their published number first, and only then report your own.
This does that against [Splink](https://moj-analytical-services.github.io/splink/),
which is the closest thing to a standard in probabilistic record linkage and is
better at inference than arche is: Fellegi-Sunter with EM-trained m and u
parameters, term frequency adjustments, the full apparatus.

That is the point of running it. arche's claim is not that it estimates better.
It is that most of the gain available in this problem is in what the records
look like before any estimator sees them. A fair way to test that claim is to
give a better estimator the same records and see what is left over.

Reproduce first
---------------
Splink's published Febrl 4 example reports, at a 0.99 match probability:

    4,959 clusters of size 2
    82 clusters of size 1

It reports no precision, recall or F1. So the reproduction target is the cluster
count, and the accuracy numbers below are computed here, the same way, for both
engines.

Same task for both
------------------
Splink's example blocks on `soc_sec_id` and compares it. `soc_sec_id` is a
near-unique synthetic identifier, and a linkage that has one is a different and
much easier problem than one that does not. Both engines therefore get it, and
both are also run without it, because the arm without it is the one that
resembles most real work.

What this cannot show
---------------------
Febrl is synthetic. Its errors came from a generator with a model of how people
mistype. Neither engine's number here is evidence about a real register, and a
gap between them is evidence about this dataset only.

Splink is also being run close to its published example rather than tuned. A
practitioner who tuned it would likely do better, and that is worth saying
plainly: this is not "arche beats Splink", it is "here is the same task, run
both ways, with the code to check it".
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

from bench_febrl import _fetch, _truth_key  # noqa: E402

OUT = _HERE / "bench_splink_febrl_result.json"
FILES = ("dataset4a.csv", "dataset4b.csv")
SPLINK_PUBLISHED = {"clusters_of_2": 4959, "clusters_of_1": 82,
                    "threshold_match_probability": 0.99}


def _truth(a_rows, b_rows) -> int:
    return len({_truth_key(r["rec_id"]) for r in a_rows}
               & {_truth_key(r["rec_id"]) for r in b_rows})


def _score_pairs(pairs, n_true, label, extra=None) -> dict:
    """pairs: iterable of (a_rec_id, b_rec_id) the engine calls a match."""
    matched, fp = set(), 0
    for a, b in pairs:
        if _truth_key(a) == _truth_key(b):
            matched.add(_truth_key(a))
        else:
            fp += 1
    tp = len(matched)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / n_true if n_true else 0.0
    out = {"engine": label, "true_merges": tp, "false_merges": fp,
           "precision": round(prec, 4), "recall": round(rec, 4),
           "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}
    out.update(extra or {})
    return out


# ---------------------------------------------------------------- splink ----
def run_splink(a_rows, b_rows, *, with_ssn: bool) -> tuple[list, dict]:
    import pandas as pd
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    def frame(rows):
        return pd.DataFrame([{
            "unique_id": r["rec_id"],
            "given_name": r.get("given_name") or None,
            "surname": r.get("surname") or None,
            "date_of_birth": r.get("date_of_birth") or None,
            "soc_sec_id": r.get("soc_sec_id") or None,
            "street_number": r.get("street_number") or None,
            "address_1": r.get("address_1") or None,
            "postcode": r.get("postcode") or None,
            "state": r.get("state") or None,
        } for r in rows])

    df_a, df_b = frame(a_rows), frame(b_rows)

    # Splink's own blocking rules from the published example.
    blocking = [
        block_on("given_name", "surname"),
        "l.given_name = r.surname and l.surname = r.given_name",
        block_on("date_of_birth"),
        block_on("state", "address_1"),
        block_on("street_number", "address_1"),
        block_on("postcode"),
    ]
    comparisons = [
        cl.NameComparison("given_name").configure(term_frequency_adjustments=True),
        cl.NameComparison("surname").configure(term_frequency_adjustments=True),
        cl.DateOfBirthComparison("date_of_birth", input_is_string=True,
                                 datetime_format="%Y%m%d"),
        cl.ExactMatch("street_number").configure(term_frequency_adjustments=True),
        cl.DamerauLevenshteinAtThresholds("postcode", [1, 2]).configure(
            term_frequency_adjustments=True),
    ]
    if with_ssn:
        blocking.insert(3, block_on("soc_sec_id"))
        comparisons.append(cl.DamerauLevenshteinAtThresholds("soc_sec_id", [1, 2]))

    settings = SettingsCreator(
        link_type="link_only",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=blocking,
        retain_intermediate_calculation_columns=False,
    )
    linker = Linker([df_a, df_b], settings, db_api=DuckDBAPI(),
                    input_table_aliases=["a", "b"])

    deterministic = [block_on("given_name", "surname", "date_of_birth")]
    if with_ssn:
        deterministic.insert(0, block_on("soc_sec_id"))
    linker.training.estimate_probability_two_random_records_match(
        deterministic, recall=0.8)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6)
    for rule in (block_on("date_of_birth"), block_on("postcode")):
        linker.training.estimate_parameters_using_expectation_maximisation(rule)

    preds = linker.inference.predict(threshold_match_probability=0.2)
    df = preds.as_pandas_dataframe()

    at99 = df[df["match_probability"] >= 0.99]
    pairs = list(zip(at99["unique_id_l"], at99["unique_id_r"], strict=False))
    # Splink reports clusters, not pairs. In a link_only run over two files a
    # cluster of size 2 is one matched pair, which is what makes the counts
    # comparable.
    linked = set(at99["unique_id_l"]) | set(at99["unique_id_r"])
    singletons = (len(df_a) + len(df_b)) - len(linked)
    return pairs, {"clusters_of_2": len(pairs), "clusters_of_1": singletons,
                   "edges_above_0.2": len(df)}


# ----------------------------------------------------------------- arche ----
def run_arche(a_rows, b_rows, *, with_ssn: bool) -> list:
    from arche.resolve import crosswalk

    def rec(r):
        addr = " ".join(x for x in (r.get("street_number"), r.get("address_1"),
                                    r.get("address_2"), r.get("suburb"),
                                    r.get("postcode"), r.get("state")) if x)
        out = {"id": r["rec_id"],
               "name": " ".join(x for x in (r.get("given_name"),
                                            r.get("surname")) if x),
               "address": addr,
               "birth_date": r.get("date_of_birth", "")}
        if with_ssn:
            out["national_id"] = r.get("soc_sec_id", "")
        return out

    res = crosswalk([rec(r) for r in a_rows], [rec(r) for r in b_rows],
                    entity="person", id_field="id")
    return [(e["a_id"], e["b_id"]) for e in res["matches"]
            if e["decision"] == "match"]


def main() -> int:
    warnings.filterwarnings("ignore")
    a_rows, b_rows = (list(_fetch(f)) for f in FILES)
    n_true = _truth(a_rows, b_rows)
    print(f"  Febrl 4: {len(a_rows):,} x {len(b_rows):,}, {n_true:,} true pairs\n",
          flush=True)

    results = []
    for with_ssn in (True, False):
        tag = "with soc_sec_id" if with_ssn else "without soc_sec_id"
        print(f"  ===== {tag}", flush=True)

        sp_pairs, sp_meta = run_splink(a_rows, b_rows, with_ssn=with_ssn)
        if with_ssn:
            print(f"    Splink published : {SPLINK_PUBLISHED['clusters_of_2']} "
                  f"clusters of 2, {SPLINK_PUBLISHED['clusters_of_1']} of 1")
            print(f"    reproduced here  : {sp_meta['clusters_of_2']} of 2, "
                  f"{sp_meta['clusters_of_1']} of 1")
        r = _score_pairs(sp_pairs, n_true, f"splink ({tag})", sp_meta)
        results.append(r)
        print(f"    splink  true {r['true_merges']:>5}  false {r['false_merges']:>4}"
              f"  precision {r['precision']:.4f}  recall {r['recall']:.4f}"
              f"  F1 {r['f1']:.4f}", flush=True)

        ar_pairs = run_arche(a_rows, b_rows, with_ssn=with_ssn)
        r = _score_pairs(ar_pairs, n_true, f"arche ({tag})")
        results.append(r)
        print(f"    arche   true {r['true_merges']:>5}  false {r['false_merges']:>4}"
              f"  precision {r['precision']:.4f}  recall {r['recall']:.4f}"
              f"  F1 {r['f1']:.4f}\n", flush=True)

    OUT.write_text(json.dumps({
        "benchmark": "Febrl 4, Splink's published recipe reproduced, arche beside it",
        "splink_published": SPLINK_PUBLISHED,
        "splink_version": __import__("splink").__version__,
        "true_pairs": n_true,
        "note": ("Splink is run close to its published example rather than "
                 "tuned; a practitioner would likely do better. Febrl is "
                 "synthetic, so neither number is evidence about a real "
                 "register."),
        "arms": results,
    }, indent=2), encoding="utf-8")
    print(f"  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
