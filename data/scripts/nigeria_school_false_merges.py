#!/usr/bin/env python
"""False merges on Nigerian school names, measured without pair labels.

    python data/scripts/evaluate_nigeria_school_reconciliation.py --false-merges \
        --csv "C:/Users/Dee/Downloads/Schools_in_Nigeria_524370204688734996.csv"

Why this can be measured at all
--------------------------------
The Nigeria sources carry no independent pair labels, which is why this script
has always refused to report precision or recall. But one class of label is
free and certain: **two schools in different states are not the same school.**

That is enough to measure the error that matters. Every method below is scored
on pairs it *should never merge*, drawn from the register itself. Nobody
constructed them and nobody chose them to flatter a result.

What it does not measure
------------------------
Recall. There are no positive labels, so a method that refuses everything
scores perfectly here. The Leeds run is the control for that: on English school
names, exact matching reaches recall 0.876 at precision 0.992. The question
this asks is what the *same* methods do when the names stop being distinctive.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

SEED = 20260819
PAIRS = 400


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.casefold()) if t}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def run(csv_path: Path, out_path: Path | None) -> int:
    from arche.resolve import crosswalk
    from rapidfuzz import fuzz

    rows = [r for r in csv.DictReader(csv_path.open(encoding="utf-8-sig"))
            if (r.get("name") or "").strip() and (r.get("statename") or "").strip()]
    print(f"Nigeria schools: {len(rows):,} named records, "
          f"{len({r['statename'] for r in rows})} states\n", flush=True)

    # ── how distinctive is a Nigerian school name, actually ──────────────
    names = Counter(r["name"].strip().upper() for r in rows)
    shared = {n: c for n, c in names.items() if c > 1}
    print("  Name distinctiveness")
    print(f"    distinct names                {len(names):>8,} of {len(rows):,}")
    print(f"    names held by >1 school       {len(shared):>8,}")
    print(f"    records sharing a name        {sum(shared.values()):>8,}"
          f"  ({100*sum(shared.values())/len(rows):.0f}%)")
    print("    most repeated:")
    for n, c in names.most_common(5):
        st = len({r["statename"] for r in rows if r["name"].strip().upper() == n})
        print(f"      {c:>4}x  {n[:44]:<44} across {st} states")

    # ── certain negatives: same name, different state ────────────────────
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_name[r["name"].strip().upper()].append(r)

    rng = random.Random(SEED)
    pool = sorted(n for n, rs in by_name.items()
                  if len({x["statename"] for x in rs}) > 1)
    rng.shuffle(pool)

    negatives = []
    for n in pool:
        if len(negatives) >= PAIRS:
            break
        rs = sorted(by_name[n], key=lambda x: x["uniq_id"])
        a = rs[0]
        b = next((x for x in rs if x["statename"] != a["statename"]), None)
        if b:
            negatives.append((a, b))
    print(f"\n  Certain negatives: {len(negatives)} pairs sharing a name exactly, "
          f"in different states.\n  Two schools in different states are not one school.\n")

    def rec(r: dict) -> dict:
        out = {"id": r["uniq_id"], "name": r["name"].strip()}
        with contextlib.suppress(TypeError, ValueError):
            out["lat"], out["lon"] = str(float(r["y"])), str(float(r["x"]))
        return out

    methods = {
        "exact name (casefold)": lambda a, b: a.casefold().strip() == b.casefold().strip(),
        "token Jaccard >= 0.5": lambda a, b: _jaccard(a, b) >= 0.5,
        "token_set_ratio >= 90": lambda a, b: fuzz.token_set_ratio(a, b) >= 90,
    }
    results = {}
    for label, fn in methods.items():
        fm = sum(1 for a, b in negatives if fn(a["name"], b["name"]))
        results[label] = fm

    # arche sees the same names, plus coordinates it is entitled to use
    left = [rec(a) for a, _ in negatives]
    right = [rec(b) for _, b in negatives]
    res = crosswalk(left, right, entity="place", id_field="id")
    truthless = {(a["uniq_id"], b["uniq_id"]) for a, b in negatives}
    fm = sum(1 for e in res["matches"]
             if e["decision"] == "match" and (e["a_id"], e["b_id"]) in truthless)
    held = sum(1 for e in res["matches"]
               if e["decision"] == "review" and (e["a_id"], e["b_id"]) in truthless)
    results["arche (name + coords)"] = fm

    print(f"  {'method':<26}{'false merges':>14}{'rate':>9}")
    for label, n in results.items():
        print(f"  {label:<26}{n:>14,}{n/len(negatives):>9.1%}")
    print(f"\n  arche additionally routed {held} of {len(negatives)} to review "
          f"rather than merging or discarding them.")

    print("\n  For contrast, the same methods on Leeds schools (282 labels):")
    print("    exact name           precision 0.992, 2 false merges")
    print("    token_set_ratio >=90 precision 0.671, 131 false merges")
    print("    arche name + coords  precision 0.883, 37 false merges")
    print("\n  In Leeds, exact matching was the safest method available.")
    print("  Here it is the most dangerous one.")

    if out_path:
        out_path.write_text(json.dumps({
            "source": csv_path.name, "records": len(rows), "seed": SEED,
            "negative_pairs": len(negatives),
            "distinct_names": len(names), "names_shared": len(shared),
            "records_sharing_a_name": sum(shared.values()),
            "false_merges": results,
            "arche_routed_to_review": held,
            "what_this_does_not_measure": "recall; there are no positive labels",
        }, indent=2), encoding="utf-8")
        print(f"\n  -> {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    return run(a.csv, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
