# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Run arche against the Leipzig entity-resolution benchmarks.

Why this benchmark and not another
----------------------------------
Every accuracy number arche has published so far — Kano, London — comes from a
labelled set we built ourselves, and each measures recall: how many true pairs
we find. None can measure a **false merge**, because none knows every pair that
is *not* a match. Eighty-six labelled London pairs say nothing about what the
engine does to the other few thousand.

The Leipzig mappings are *complete*. Every pair not listed is a known non-match,
so precision is measurable here and nowhere else in this repo. The sets are
CC-BY-4.0 and used widely enough that our numbers can be read against other
people's rather than only against ourselves.

    https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution

What it found
-------------
On DBLP-ACM, out of the box with no bibliographic pack: blocking recall 0.9996,
recall 0.9960, **precision 0.8500** — 391 false merges. Those merges are almost
all recurring generic titles (``Guest editorial`` appears 8x in ACM, ``Book
reviews`` 8x, ``Reminiscences on Influential Papers`` 7x). That is the "General
Hospital" defect in a third domain, on data we neither chose nor labelled.

Year agrees on 2,224 of 2,224 true pairs and separates 213 of the false merges.
``--sweep-year`` is the control that matters: raising the weight of that field
*lowers* precision (0.876 at weight 2.0, 0.653 at weight 7.0), because a weight
is symmetric — it rewards agreement as much as it punishes disagreement, and
agreement on a year is not evidence. Some attributes refute without confirming,
and a weight cannot express one. See the roadmap's "refutation gap".

Usage
-----
    python data/scripts/benchmark_leipzig.py
    python data/scripts/benchmark_leipzig.py --sweep-year
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

_DATA = _REPO / "data" / "er_bench"

# Declared by hand: no bibliographic pack ships, so this is what an ordinary
# user would write on day one. That is the point — it measures the engine as
# adopted, not as tuned by its authors.
def _comparators(year_weight: float = 0.5) -> list[dict]:
    return [
        {"field": "title", "kind": "name", "weight": 3.0},
        {"field": "title", "kind": "tftoken", "weight": 2.0},
        {"field": "authors", "kind": "name", "weight": 2.0},
        {"field": "year", "kind": "date", "weight": year_weight},
    ]


def _refuting() -> list[dict]:
    """The same declaration, with `year` declared as a discriminator.

    Year keeps its 0.5 weight: dropping it to 0.0 buys 0.6 more precision
    points but costs 5 true matches, because the small positive contribution
    is what carries those pairs over the threshold. Refutation and scoring are
    orthogonal, so there is no reason to give up the second to get the first.
    """
    comps = _comparators()
    comps[-1]["refutes_below"] = 0.99
    return comps


def _read(name: str) -> list[dict]:
    path = _DATA / name
    if not path.exists():
        raise SystemExit(
            f"missing {path}\n"
            "Fetch DBLP-ACM from the Leipzig benchmark page (CC-BY-4.0) into "
            f"{_DATA}"
        )
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def _score(res: dict, truth: set[tuple[str, str]]) -> dict:
    pred = {(e["a_id"], e["b_id"]): e for e in res["matches"]}
    tp = {k for k, e in pred.items() if e["decision"] == "match" and k in truth}
    fp = {k for k, e in pred.items() if e["decision"] == "match" and k not in truth}
    review = {k for k, e in pred.items() if e["decision"] == "review"}
    denom = len(tp) + len(fp)
    return {
        "tp": len(tp),
        "fp": len(fp),
        "precision": len(tp) / denom if denom else 0.0,
        "recall": len(tp) / len(truth),
        # Surfaced recall counts the review queue: a pair a human is asked to
        # look at is found, just not decided. Reporting only auto-recall
        # understates a system that deliberately abstains.
        "surfaced": (len(tp) + len(review & truth)) / len(truth),
        # Blocking recall is the ceiling everything else sits under. A pair
        # never proposed cannot be recovered by any amount of scoring.
        "blocking": 1 - len(truth - set(pred)) / len(truth),
        "review": len(review),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep-year", action="store_true",
                    help="show that reweighting cannot substitute for a veto")
    args = ap.parse_args()

    from arche.resolve import crosswalk

    dblp, acm = _read("DBLP2.csv"), _read("ACM.csv")
    truth = {(r["idDBLP"], r["idACM"])
             for r in _read("DBLP-ACM_perfectMapping.csv")}
    fields = ("title", "authors", "year")
    A = [{"id": r["id"], **{f: r[f] for f in fields}} for r in dblp]
    B = [{"id": r["id"], **{f: r[f] for f in fields}} for r in acm]
    print(f"DBLP {len(A)} x ACM {len(B)}, {len(truth)} true pairs "
          f"(mapping is complete, so non-matches are known)\n")

    def report(label: str, comps: list[dict]) -> dict:
        m = _score(crosswalk(A, B, comparators=comps, id_field="id"), truth)
        print(f"  {label:30} P={m['precision']:.4f}  R={m['recall']:.4f}  "
              f"surfaced={m['surfaced']:.4f}  blocking={m['blocking']:.4f}  "
              f"(TP {m['tp']}, FP {m['fp']}, review {m['review']})", flush=True)
        return m

    if args.sweep_year:
        print("Sweeping the weight of `year`, a discriminator that agrees on "
              "100% of true pairs:\n")
        for w in (0.5, 2.0, 7.0, 25.0):
            report(f"year weight {w}", _comparators(w))
        print("\n  Precision peaks early and collapses. A weight is symmetric: "
              "it rewards\n  agreement as much as it punishes disagreement, and "
              "agreement on a year is\n  not evidence. Turning the field up "
              "turns up the noise it sits in.")
        return 0

    # The headline comparison: the same declaration, with and without the year
    # declared as a refutation rather than scored as a preference.
    base = report("baseline (year scored)", _comparators())
    veto = report("year refutes_below 0.99", _refuting())
    print(f"\n  precision {base['precision']:.4f} -> {veto['precision']:.4f}, "
          f"recall {base['recall']:.4f} -> {veto['recall']:.4f}")
    print(f"  {base['fp'] - veto['fp']} false merges removed, "
          f"{base['tp'] - veto['tp']} true matches lost")

    # Emit the result beside the other lanes' result files. Without this the
    # published 0.9506 is a number in a README that a reader has to take on
    # trust, and it is easy to miss that it is the *refuting* configuration:
    # out of the box, with no discriminator declared, precision is 0.8500.
    import json as _json
    out = _REPO / "data" / "er_bench" / "benchmark_leipzig_result.json"
    out.write_text(_json.dumps({
        "benchmark": "Leipzig DBLP-ACM (complete mapping)",
        "source_url": ("https://dbs.uni-leipzig.de/research/projects/"
                       "benchmark-datasets-for-entity-resolution"),
        "records_dblp": len(dblp), "records_acm": len(acm),
        "true_pairs": len(truth),
        "configurations": {
            "out_of_the_box": base,
            "year_refutes_below_0.99": veto,
        },
        "note": "0.9506 is the refuting configuration and requires the caller "
                "to declare refutes_below on year. Out of the box the same "
                "pipeline scores 0.8500 with 391 false merges.",
    }, indent=2, default=float), encoding="utf-8")
    print(f"  -> {out.name}")

    # The refutation evidence: how clean is `year` as a discriminator, and how
    # much of the false-merge mass does it separate?
    by_title: dict[str, list[dict]] = {}
    for r in acm:
        by_title.setdefault(r["title"].strip().lower(), []).append(r)
    collisions = non_pair = by_year = 0
    for r in dblp:
        for s in by_title.get(r["title"].strip().lower(), []):
            collisions += 1
            if (r["id"], s["id"]) not in truth:
                non_pair += 1
                by_year += r["year"].strip() != s["year"].strip()

    idx_a = {r["id"]: r for r in dblp}
    idx_b = {r["id"]: r for r in acm}
    agree = sum(1 for a, b in truth
                if idx_a[a]["year"].strip() == idx_b[b]["year"].strip())
    print(f"\n  year agrees on {agree}/{len(truth)} true pairs "
          f"({100 * agree / len(truth):.2f}%)")
    print(f"  exact title collisions {collisions}, of which {non_pair} are not "
          f"true pairs; {by_year} of those disagree on year")
    print("\n  most repeated ACM titles (where the false merges live):")
    repeated = Counter(r["title"].strip().lower() for r in acm)
    for title, n in sorted(repeated.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {n:>3}x  {title[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
