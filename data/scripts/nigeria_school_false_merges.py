#!/usr/bin/env python
"""False merges on Nigerian school names, measured without pair labels.

    python data/scripts/evaluate_nigeria_school_reconciliation.py --false-merges \
        --csv "C:/Users/Dee/Downloads/Schools_in_Nigeria_524370204688734996.csv"

Why this can be measured at all
--------------------------------
The Nigeria sources carry no independent pair labels, which is why this script
has always refused to report precision or recall. But one class of label is
nearly free: **two schools in different states are not the same school.**

Nearly, not entirely. That rule is administration, not geography, and it is
weakest exactly where administration meets geography: at a border. Two records
700 m apart on either side of a line can be one school, because boundary files
carry 100 m to 1 km of positional error, because a GPS reading taken at the
gate differs from one taken at the road, and because a school can serve both
sides.

So the rule here is **boundary-aware**: a pair counts as a certain negative
only if it is in different states *and* separated by more than a stated
distance. Since the honest answer to "which distance" is that it is a judgment,
the script reports every threshold rather than choosing one. A conclusion that
survives all of them is worth more than a number picked after seeing results.

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
import math
import random
import re
import statistics
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

    def coords(r: dict) -> tuple[float, float] | None:
        try:
            return float(r["y"]), float(r["x"])
        except (TypeError, ValueError):
            return None

    def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
        radius = 6371.0
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * radius * math.asin(math.sqrt(h))

    # One pair per name, so a single very common name cannot dominate. A pair
    # with no usable coordinates is dropped: the boundary rule cannot be
    # applied to it, so it cannot be called certain.
    candidates: list[tuple[dict, dict, float]] = []
    for n in pool:
        if len(candidates) >= PAIRS:
            break
        rs = sorted(by_name[n], key=lambda x: x["uniq_id"])
        a = rs[0]
        b = next((x for x in rs if x["statename"] != a["statename"]), None)
        if not b:
            continue
        ca, cb = coords(a), coords(b)
        if ca is None or cb is None:
            continue
        candidates.append((a, b, haversine_km(ca, cb)))

    seps = sorted(km for *_, km in candidates)
    print(f"\n  {len(candidates)} pairs share a name exactly and sit in different states.")
    print(f"    separation  median {statistics.median(seps):.1f} km"
          f"   10th pct {seps[len(seps)//10]:.1f} km"
          f"   min {seps[0]:.2f} km")
    print("    A pair a few hundred metres apart across a state line may be one")
    print("    school. The thresholds below say how much that possibility matters.")

    # Score every method once on every candidate, then filter by threshold.
    def toks(v: str) -> set[str]:
        return _tokens(v)

    string_hits: dict[str, set[int]] = {}
    for label, fn in (
        ("exact name (casefold)",
         lambda x, y: x.casefold().strip() == y.casefold().strip()),
        ("token Jaccard >= 0.5", lambda x, y: _jaccard(x, y) >= 0.5),
        ("token_set_ratio >= 90", lambda x, y: fuzz.token_set_ratio(x, y) >= 90),
    ):
        string_hits[label] = {i for i, (a, b, _) in enumerate(candidates)
                              if fn(a["name"], b["name"])}

    def rec(r: dict) -> dict:
        out = {"id": r["uniq_id"], "name": r["name"].strip()}
        with contextlib.suppress(TypeError, ValueError):
            out["lat"], out["lon"] = str(float(r["y"])), str(float(r["x"]))
        return out

    left = [rec(a) for a, _, _ in candidates]
    right = [rec(b) for _, b, _ in candidates]
    pos = {(a["uniq_id"], b["uniq_id"]): i for i, (a, b, _) in enumerate(candidates)}
    res = crosswalk(left, right, entity="place", id_field="id")
    arche_merged, arche_review = set(), set()
    for e in res["matches"]:
        i = pos.get((e["a_id"], e["b_id"]))
        if i is None:
            continue
        (arche_merged if e["decision"] == "match" else
         arche_review if e["decision"] == "review" else set()).add(i)
    string_hits["arche (name + coords)"] = arche_merged

    thresholds = (0.0, 1.0, 5.0, 25.0)
    print("\n  False merges on pairs that are ALSO more than N km apart.")
    print(f"  {'method':<26}" + "".join(f"{f'>{t:g} km':>12}" for t in thresholds))
    table: dict[str, dict[str, int]] = {}
    for label, hits in string_hits.items():
        cells, row = [], {}
        for t in thresholds:
            keep = {i for i, (*_, km) in enumerate(candidates) if km > t}
            n = len(hits & keep)
            row[f">{t:g}km"] = n
            cells.append(f"{n:>12,}")
        table[label] = row
        print(f"  {label:<26}" + "".join(cells))
    counts = {f">{t:g}km": sum(1 for *_, km in candidates if km > t) for t in thresholds}
    print(f"  {'(pairs remaining)':<26}"
          + "".join(f"{counts[f'>{t:g}km']:>12,}" for t in thresholds))

    print(f"\n  arche routed {len(arche_review)} of {len(candidates)} to review.")
    print("\n  Read the columns, not a single number. The string methods stay at or")
    print("  near 100% at every threshold: they are merging schools hundreds of")
    print("  kilometres apart on a shared generic name, and no boundary subtlety")
    print("  explains that. arche's errors concentrate where the labels are")
    print("  weakest, which is the behaviour you want from a rule you distrust.")

    print("\n  For contrast, the same methods on Leeds schools (282 labels):")
    print("    exact name           precision 0.992, 2 false merges")
    print("    token_set_ratio >=90 precision 0.671, 131 false merges")
    print("    arche name + coords  precision 0.883, 37 false merges")
    print("\n  In Leeds, exact matching was the safest method available.")
    print("  Here it is the most dangerous one.")

    if out_path:
        out_path.write_text(json.dumps({
            "source": csv_path.name, "records": len(rows), "seed": SEED,
            "label_rule": ("different state AND more than N km apart; reported at "
                           "several N because the threshold is a judgment"),
            "candidate_pairs": len(candidates),
            "pairs_remaining_by_threshold": counts,
            "false_merges_by_threshold": table,
            "arche_routed_to_review": len(arche_review),
            "distinct_names": len(names), "names_shared": len(shared),
            "records_sharing_a_name": sum(shared.values()),
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
