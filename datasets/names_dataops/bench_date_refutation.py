# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does declaring `refutes_below` on the person pack's date comparator help?

The Parrish linkage set said yes: precision 0.9962 -> 1.0000. One dataset is a
data point, and the shipped pack deliberately does not declare refutation, so a
second opinion was owed before that decision is revisited.

Why this is not simply "run it on NCVR"
---------------------------------------
`bench_name_frequency.py` already builds NCVR pairs, and reusing them would have
been meaningless twice over:

* its **negatives are selected for disagreeing on birth year**
  (`a["birth_year"] != b["birth_year"]`, there to stop duplicate registrations
  becoming mislabelled negatives). A comparator that reads birth year would
  separate 100% of them by construction.
* its **positives are one record recorded twice**, so the year always agrees and
  refutation can never cost anything.

Both arms would have reported a perfect result for reasons that have nothing to
do with whether refutation is a good idea.

So this script rebuilds the pairs:

* negatives drop the birth-year condition. Same surname, different NCID,
  different first name. Now some negatives share a birth year and some do not,
  which is the only way the field can be evidence rather than the label.
* positives get a **stated** rate of year disagreement, swept rather than
  chosen, because the cost of refutation is entirely a function of how often
  true pairs disagree on the field and NCVR cannot tell us that rate.

What this still cannot measure
------------------------------
**NCVR has no date of birth.** It carries `birth_year` and nothing finer. The
person pack declares a `date` comparator over a full date, where a year is
roughly a hundred times less selective, and the near-miss grading that a full
date gets (0.35 for one keying slip) never fires at year precision.

So this measures refutation on a *year*, which is the field `reconcile.py`
already warns about by name: on DBLP-ACM, publication year agrees on every true
pair and separates half the false merges, and raising its weight lowers
precision because thousands of records share one. Read the result as evidence
about coarse fields, not as a second Parrish.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_HERE))

from arche.resolve import crosswalk  # noqa: E402
from bench_name_frequency import (  # noqa: E402
    BANDS,
    PER_BAND,
    SEED,
    _band_of,
    _clean,
    _fetch,
    _usable,
)

OUT = _HERE / "bench_date_refutation_result.json"

# How often a true pair disagrees on birth year. Unknown for NCVR, and the whole
# cost of refutation lives in it, so it is swept and reported rather than picked.
ERROR_RATES = (0.0, 0.02, 0.05, 0.10)

BASE = [
    {"field": "name", "kind": "name", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
]
WITH_DATE = [*BASE, {"field": "birth_date", "kind": "date", "weight": 2.0}]
WITH_REFUTATION = [*BASE, {"field": "birth_date", "kind": "date", "weight": 2.0,
                           "refutes_below": 0.5}]


def _distinct_pair(recs: list[dict]) -> tuple[dict, dict] | None:
    """Two records that are certainly different people, without reading the year.

    The original guarded against duplicate registrations by requiring different
    birth years. That is the field under test here, so the guard has to be
    something else: a different NCID and a different first name. A duplicate
    registration of one person almost always keeps the first name, so this is
    weaker than the original but not circular, which is the trade being made.
    """
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            a, b = recs[i], recs[j]
            if (a["ncid"] != b["ncid"]
                    and _clean(a["first_name"]) != _clean(b["first_name"])):
                return a, b
    return None


def _name(r: dict) -> str:
    return " ".join(p for p in (_clean(r["first_name"]), _clean(r["middle_name"]),
                                _clean(r["last_name"])) if p)


def build(rows: list[dict], error_rate: float) -> list[dict]:
    rng = random.Random(SEED)
    rows = [r for r in rows if _usable(r)]
    by_surname: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_surname[_clean(r["last_name"])].append(r)

    in_band: dict[str, list[str]] = defaultdict(list)
    for sur, recs in by_surname.items():
        band = _band_of(len(recs))
        if band:
            in_band[band].append(sur)
    for band in in_band:
        in_band[band].sort()
        rng.shuffle(in_band[band])

    pairs: list[dict] = []
    for label, _, _ in BANDS:
        pool = in_band[label]
        taken = 0
        for sur in pool:
            if taken >= PER_BAND:
                break
            recs = sorted(by_surname[sur], key=lambda r: r["ncid"])
            rng.shuffle(recs)
            got = _distinct_pair(recs)
            if got:
                a, b = got
                pairs.append({"cls": "neg", "a": _name(a), "b": _name(b),
                              "ya": a["birth_year"], "yb": b["birth_year"]})
                taken += 1

        cands = [r for sur in pool for r in by_surname[sur]
                 if len(_clean(r["middle_name"])) >= 2
                 and _clean(r["middle_name"]).isalpha()]
        rng.shuffle(cands)
        for k, r in enumerate(cands[:PER_BAND]):
            first, mid, last = (_clean(r["first_name"]), _clean(r["middle_name"]),
                                _clean(r["last_name"]))
            other = (f"{first} {last}" if k % 2 == 0 else f"{first} {mid[0]} {last}")
            year = r["birth_year"]
            # A stated fraction of true pairs disagree on the year, the way a
            # register with two sources does.
            shown = year
            if rng.random() < error_rate:
                shown = str(int(year) + rng.choice((-1, 1)))
            pairs.append({"cls": "pos", "a": f"{first} {mid} {last}", "b": other,
                          "ya": year, "yb": shown})
    return pairs


def score(pairs: list[dict], comparators: list[dict]) -> dict:
    left = [{"id": f"L{i}", "name": p["a"], "birth_date": p["ya"]}
            for i, p in enumerate(pairs)]
    right = [{"id": f"R{i}", "name": p["b"], "birth_date": p["yb"]}
             for i, p in enumerate(pairs)]
    res = crosswalk(left, right, entity="person", id_field="id",
                    comparators=comparators)
    designated = {f"L{i}": f"R{i}" for i, p in enumerate(pairs) if p["cls"] == "pos"}
    npos = len(designated)

    merged: dict[str, str] = {}
    for e in res["matches"]:
        if e["decision"] != "match":
            continue
        cur = merged.get(e["a_id"])
        if cur is None or e["score"] > cur[1]:
            merged[e["a_id"]] = (e["b_id"], e["score"])
    merged = {k: v[0] for k, v in merged.items()}

    tp = sum(1 for a, b in merged.items() if designated.get(a) == b)
    fp = len(merged) - tp
    # The diagnostic that explains the result. Refutation can only act on a
    # pair whose other evidence kept it alive despite the date disagreeing; if
    # nothing is ever flagged, the weight already removed them and declaring
    # `refutes_below` is a no-op.
    flagged = sum(1 for e in res["matches"]
                  if "birth_date_conflict" in (e.get("evidence") or {}))
    return {"merged": len(merged), "true_merges": tp, "false_merges": fp,
            "conflicts_flagged": flagged,
            "positives": npos,
            "precision": round(tp / len(merged), 4) if merged else 0.0,
            "recall": round(tp / npos, 4) if npos else 0.0,
            "f1": round(2 * tp / (2 * tp + fp + (npos - tp)), 4) if tp else 0.0}


def main() -> int:
    rows = _fetch()
    print(f"  {len(rows):,} registrations\n")

    base_pairs = build(rows, 0.0)
    nneg = sum(1 for p in base_pairs if p["cls"] == "neg")
    agree = sum(1 for p in base_pairs if p["cls"] == "neg" and p["ya"] == p["yb"])
    print(f"  {nneg} negatives, {sum(1 for p in base_pairs if p['cls']=='pos')} positives")
    print(f"  negatives that SHARE a birth year: {agree} ({agree/nneg:.1%})")
    print("  That share is the whole point. In the existing benchmark it is 0%,")
    print("  because the negatives were selected for disagreeing.\n")

    results: dict[str, dict] = {}
    for rate in ERROR_RATES:
        pairs = build(rows, rate)
        print(f"  --- {rate:.0%} of true pairs disagree on the year")
        print(f"  {'arm':<26}{'merged':>8}{'true':>7}{'false':>7}"
              f"{'precision':>11}{'recall':>9}{'F1':>8}{'refuted':>9}")
        for label, spec in (("name only", BASE),
                            ("+ year, weighted", WITH_DATE),
                            ("+ year, refuting", WITH_REFUTATION)):
            r = score(pairs, spec)
            results[f"{rate}|{label}"] = r
            print(f"  {label:<26}{r['merged']:>8}{r['true_merges']:>7}"
                  f"{r['false_merges']:>7}{r['precision']:>11.4f}"
                  f"{r['recall']:>9.4f}{r['f1']:>8.4f}"
                  f"{r['conflicts_flagged']:>9}")
        print()

    OUT.write_text(json.dumps({
        "benchmark": "NCVR, refutation on a birth YEAR (not a date of birth)",
        "what_it_cannot_measure": (
            "refutation on a date of birth: NCVR carries only birth_year, so "
            "the near-miss grading a full date gets never fires, and a year is "
            "far less selective than a date"
        ),
        "negatives_rebuilt": (
            "the existing benchmark selects negatives for disagreeing on birth "
            "year, which would make this circular; here the condition is dropped"
        ),
        "positive_error_rate": "swept, not chosen; NCVR cannot supply the real one",
        "seed": SEED, "arms": results,
    }, indent=2), encoding="utf-8")
    print(f"  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
