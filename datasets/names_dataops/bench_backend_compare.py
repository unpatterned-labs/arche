# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does `crosswalk(backend="splink")` actually deliver Splink's advantage?

Three arms per dataset, and the gaps between them are the whole point:

* **arche** the shipped engine.
* **derived** `crosswalk(backend="splink", splink_settings="derive")`, the
  configuration inferred from an arche comparator pack.
* **adapter** `crosswalk(backend="splink", splink_settings=...)` handed the
  SAME `SettingsCreator` and training recipe the hand-written benchmark in this
  directory uses. Not a copy of them: the objects are imported from
  `bench_splink_febrl.py` and `bench_splink_nigeria.py`, so if the adapter is
  faithful the two arms produce the same counts and there is nothing here that
  can drift out of agreement with them.

`arche` against `derived` says whether inferring a configuration is worth
reaching for. `adapter` against the hand-written number says whether arche's
wrapper costs anything at all.

`historical_50k` is not run here. Every attempt on the machine this was written
on was killed by the operating system before it produced a number, both for the
derived path and for arche's own engine, so an arm for it would be a blank
column rather than a result. `bench_splink_historical.py` still runs Splink on
it alone.

    uv run python datasets/names_dataops/bench_backend_compare.py febrl
    uv run python datasets/names_dataops/bench_backend_compare.py nigeria

`ARCHE_BENCH_POPULATION` shrinks the Nigerian filler population for a faster
run; the default is the one `bench_splink_nigeria.py` publishes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_HERE))

OUT = _HERE / "bench_backend_compare_result.json"

# Published by the scripts named, quoted so the arms sit together on one page.
#
# The Febrl figure is the mean of two consecutive runs of
# `bench_splink_febrl.run_splink(with_ssn=False)`, which scored 0.9534 and
# 0.9528. It moves between runs because that recipe calls
# `estimate_u_using_random_sampling` without a seed, so anyone re-running it
# should expect the third decimal to differ and should not read a change of
# that size as a regression.
HAND = {
    "febrl_no_ssn": {"precision": 1.0000, "recall": 0.9531,
                     "runs": [0.9534, 0.9528],
                     "source": "bench_splink_febrl.py, p >= 0.99, unseeded"},
    "nigeria": {"true": 190, "false": 0,
                "source": "bench_splink_nigeria.py, p >= 0.9"},
}


def _timed(label, fn):
    t0 = time.time()
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001 - report the failure, never hide it
        print(f"  {label:<9} FAILED: {type(exc).__name__}: "
              f"{str(exc).splitlines()[0][:160]}", flush=True)
        return None, {"arm": label, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return out, {"arm": label, "seconds": round(time.time() - t0, 1)}


# ----------------------------------------------------------------- febrl ----

def febrl() -> list[dict]:
    """Febrl 4 without `soc_sec_id`, the arm that resembles real work."""
    from arche.resolve import crosswalk
    from bench_splink_febrl import (
        FILES,
        _fetch,
        _score_pairs,
        _truth,
        run_arche,
        splink_record,
        splink_settings,
        splink_train,
    )

    a_rows, b_rows = (list(_fetch(f)) for f in FILES)
    n_true = _truth(a_rows, b_rows)
    print(f"  febrl 4: {len(a_rows):,} x {len(b_rows):,}, {n_true:,} true pairs",
          flush=True)

    # arche's own engine flattens the file into `name` and `address` blobs;
    # that IS its schema and the derived arm inherits it. The adapter arm keeps
    # the columns the Splink recipe was written against, which is the point.
    splink_records = [splink_record(r) for r in (*a_rows, *b_rows)]
    half = len(a_rows)

    rows = []

    def score(pairs, label, meta):
        row = _score_pairs(pairs, n_true, label)
        row.update(meta)
        rows.append(row)
        print(f"  {label:<16} true {row['true_merges']:>5}  "
              f"false {row['false_merges']:>4}  precision {row['precision']:.4f}  "
              f"recall {row['recall']:.4f}  ({meta.get('seconds')}s)", flush=True)

    pairs, meta = _timed("arche", lambda: run_arche(a_rows, b_rows,
                                                    with_ssn=False))
    if pairs is not None:
        score(pairs, "arche", meta)

    # Both Splink arms predict down to 0.2 and are then cut at several
    # probabilities. A derived configuration and a hand-written one estimate
    # `probability_two_random_records_match` differently, which shifts the
    # whole scale, so reading one arm at a single threshold says as much about
    # the prior as about the matching.
    def edges(res):
        return [(e["a_id"], e["b_id"], e["score"]) for e in res["matches"]]

    def sweep(rows_, label, meta):
        for thr in (0.99, 0.9, 0.5):
            score([(a, b) for a, b, s in rows_ if s >= thr],
                  f"{label} p>={thr}", meta)

    got, meta = _timed("derived", lambda: edges(crosswalk(
        _arche_records(a_rows), _arche_records(b_rows), entity="person",
        id_field="id", backend="splink", splink_settings="derive",
        threshold=0.99, review_margin=0.79)))
    if got is not None:
        sweep(got, "derived", meta)

    got, meta = _timed("adapter", lambda: edges(crosswalk(
        splink_records[:half], splink_records[half:], id_field="id",
        backend="splink", splink_settings=splink_settings(with_ssn=False),
        splink_train=lambda ln: splink_train(ln, with_ssn=False),
        threshold=0.99, review_margin=0.79)))
    if got is not None:
        sweep(got, "adapter", meta)

    hand = HAND["febrl_no_ssn"]
    print(f"  {'hand':<16} precision {hand['precision']:.4f}  "
          f"recall {hand['recall']:.4f}   ({hand['source']})", flush=True)
    return rows


def _arche_records(rows):
    """The Febrl file in arche's `person` pack schema.

    One `name` blob and one `address` blob, which is what `bench_splink_febrl`'s
    arche arm builds. Splink's own recipe compares `given_name` and `surname`
    as separate columns and learns separate m and u for each; the derived arm
    cannot, because by the time it runs those columns are gone.
    """
    out = []
    for r in rows:
        addr = " ".join(x for x in (r.get("street_number"), r.get("address_1"),
                                    r.get("address_2"), r.get("suburb"),
                                    r.get("postcode"), r.get("state")) if x)
        out.append({"id": r["rec_id"],
                    "name": " ".join(x for x in (r.get("given_name"),
                                                 r.get("surname")) if x),
                    "address": addr,
                    "birth_date": r.get("date_of_birth", "")})
    return out


# --------------------------------------------------------------- nigeria ----

def nigeria() -> list[dict]:
    import bench_splink_nigeria as bn
    from arche.resolve import crosswalk

    override = os.environ.get("ARCHE_BENCH_POPULATION")
    if override:
        bn.POPULATION = int(override)

    negatives, positives, filler = bn.build()
    records, neg_ids, pos_ids = bn._records(negatives, positives, filler)
    print(f"\n  nigeria: {len(records):,} records, {len(neg_ids)} certain "
          f"negatives, {len(pos_ids)} constructed positives "
          f"(POPULATION={bn.POPULATION})", flush=True)

    rows = []

    def report(merged, label, meta, at):
        tp, fp = len(merged & pos_ids), len(merged & neg_ids)
        rows.append({"arm": label, "at": at, "true": tp, "false": fp,
                     "positives": len(pos_ids), "negatives": len(neg_ids),
                     **meta})
        print(f"  {label + ' ' + at:<22} true {tp:>4} of {len(pos_ids)}   "
              f"FALSE {fp:>4} of {len(neg_ids)}  ({meta.get('seconds')}s)",
              flush=True)

    def run(**kw):
        res = crosswalk(records, records, id_field="id", **kw)
        return [(bn.norm((e["a_id"], e["b_id"])), e["score"], e["decision"])
                for e in res["matches"] if e["a_id"] != e["b_id"]]

    def at_probability(scored, thr):
        return {p for p, s, _ in scored if s >= thr}

    # arche's own engine is scored on its DECISION, not on a raw score cut. Its
    # gate and its distance veto demote a pair to `review` without lowering the
    # number, so reading the score alone reports merges the engine refused to
    # make.
    scored, meta = _timed("arche", lambda: run(entity="place"))
    if scored is not None:
        report({p for p, _, d in scored if d == "match"}, "arche", meta,
               "match")
        report({p for p, _, d in scored if d in ("match", "review")}, "arche",
               meta, "match+review")

    # Both Splink arms predict down to 0.01 so the same edge set can be cut at
    # several probabilities; `bench_splink_nigeria.py` reports at 0.9 and that
    # is the row to compare against.
    scored, meta = _timed(
        "derived", lambda: run(entity="place", backend="splink",
                               splink_settings="derive",
                               threshold=0.9, review_margin=0.89))
    if scored is not None:
        for thr in (0.99, 0.9, 0.5):
            report(at_probability(scored, thr), "derived", meta, f"p>={thr}")

    scored, meta = _timed(
        "adapter", lambda: run(backend="splink",
                               splink_settings=bn.splink_settings(),
                               splink_train=bn.splink_train,
                               threshold=0.9, review_margin=0.89))
    if scored is not None:
        for thr in (0.99, 0.9, 0.5):
            report(at_probability(scored, thr), "adapter", meta, f"p>={thr}")

    hand = HAND["nigeria"]
    print(f"  {'hand p>=0.9':<22} true {hand['true']:>4}          "
          f"FALSE {hand['false']:>4}         ({hand['source']})",
          flush=True)
    return rows


def main(argv: list[str]) -> int:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    which = set(argv[1:]) or {"febrl", "nigeria"}
    results = {}
    if "febrl" in which:
        results["febrl_no_ssn"] = febrl()
    if "nigeria" in which:
        results["nigeria"] = nigeria()
    results["hand_configured_reference"] = HAND
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    previous.update(results)
    OUT.write_text(json.dumps(previous, indent=2), encoding="utf-8")
    print(f"\n  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
