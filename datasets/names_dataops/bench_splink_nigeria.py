# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Splink and arche on Nigerian school names, where names stop discriminating.

The two Splink comparisons so far were on Febrl and `historical_50k`, and Splink
won both. Both are datasets where a name is a reasonably distinctive thing. This
is the one where it is not, and it is the case arche's design is actually about:
`COMMUNITY PRIMARY SCHOOL` occurs 200 times across 21 states, `LGEA PRIMARY
SCHOOL` 120 times across 11.

Splink already does the obvious thing here, and it should be said plainly:
`NameComparison(...).configure(term_frequency_adjustments=True)` is term
frequency weighting, the same idea as arche's `tftoken`, and it has been in
Splink for years. So the question is not whether one tool weights by frequency
and the other does not. Both do. The question is whether arche's extra
apparatus, a distinctive-signal *gate* that refuses a merge outright rather than
scoring it down, catches something a well-weighted score does not.

The labels
----------
The register carries no positive labels, which is why the standing benchmark
refuses to report recall. Two label sources are used instead, and they are not
the same kind of thing:

* **Negatives, observed.** Two schools in different states are not the same
  school. 400 pairs sharing a name exactly across a state line. Nobody
  constructed these and nobody chose them to flatter a result.
* **Positives, constructed.** One real record, recorded twice, with an ordinary
  recording difference applied. These measure whether an engine can still find
  anything, which is the control a false-merge count needs: an engine that
  merges nothing scores zero false merges and is useless.

Read the two columns together. Neither alone says anything.
"""
from __future__ import annotations

import csv
import json
import math
import random
import sys
import warnings
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

CSV_PATH = _REPO / "data" / "_cache" / "schools" / "nigeria_schools.csv"
OUT = _HERE / "bench_splink_nigeria_result.json"
SEED = 20260816
PAIRS = 400
POSITIVES = 400
# Enough of the register for term frequency to mean something.
POPULATION = 12000


def haversine_km(a, b) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def coords(r):
    try:
        return float(r["y"]), float(r["x"])
    except (TypeError, ValueError):
        return None


def build():
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    by_name = defaultdict(list)
    for r in rows:
        n = (r["name"] or "").strip().casefold()
        if n and coords(r):
            by_name[n].append(r)

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

    # Positives: one record, recorded twice. The second copy loses its leading
    # type word or gains a common abbreviation, which is what these registers
    # actually differ by.
    singles = [rs[0] for n, rs in sorted(by_name.items()) if len(rs) == 1]
    rng.shuffle(singles)
    positives = []
    for k, r in enumerate(singles[:POSITIVES]):
        name = r["name"].strip()
        alt = (name.replace("PRIMARY", "PRY", 1) if k % 2 == 0
               else " ".join(name.split()[1:]) or name)
        if alt.strip().casefold() == name.casefold():
            continue
        positives.append((r, alt))

    others = [r for r in rows if coords(r)]
    rng.shuffle(others)
    return negatives, positives, others[:POPULATION]


def _records(negatives, positives, filler):
    """One flat list. ids encode the role so scoring can find them again."""
    out, neg_ids, pos_ids = [], [], []
    for i, (a, b) in enumerate(negatives):
        for side, r in (("a", a), ("b", b)):
            c = coords(r)
            out.append({"id": f"neg{i}{side}", "name": r["name"].strip(),
                        "lat": c[0], "lon": c[1]})
        neg_ids.append((f"neg{i}a", f"neg{i}b"))
    for i, (r, alt) in enumerate(positives):
        c = coords(r)
        out.append({"id": f"pos{i}a", "name": r["name"].strip(),
                    "lat": c[0], "lon": c[1]})
        # Same school, so the same coordinate, jittered the way a second survey
        # would differ rather than agreeing to the metre.
        out.append({"id": f"pos{i}b", "name": alt,
                    "lat": c[0] + 0.0009, "lon": c[1] + 0.0009})
        pos_ids.append((f"pos{i}a", f"pos{i}b"))
    for j, r in enumerate(filler):
        c = coords(r)
        out.append({"id": f"fill{j}", "name": r["name"].strip(),
                    "lat": c[0], "lon": c[1]})
    return out, set(neg_ids), set(pos_ids)


def norm(p):
    a, b = p
    return (a, b) if a <= b else (b, a)


def splink_settings():
    """The hand-written configuration, in one place.

    `bench_backend_compare.py` runs the SAME object through
    `crosswalk(backend="splink")`. If the adapter is faithful the two arms
    produce identical counts, and a second copy of these settings living over
    there would be able to drift until they no longer did.
    """
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on

    return SettingsCreator(
        link_type="dedupe_only",
        blocking_rules_to_generate_predictions=[
            # Reaches the negatives, which share a name exactly.
            block_on("name"),
            block_on("substr(name,1,8)"),
            # Reaches the positives, whose names differ but whose coordinates
            # agree to about a hundred metres. arche's place pack gets the same
            # coordinates, so withholding them here would be the harness
            # choosing the winner.
            block_on("round(lat,2)", "round(lon,2)"),
            block_on("round(lat,1)", "round(lon,1)"),
        ],
        comparisons=[
            # Term frequency on, which is the fair fight: this is Splink's own
            # answer to a name that repeats.
            cl.NameComparison("name").configure(term_frequency_adjustments=True),
            cl.DistanceInKMAtThresholds("lat", "lon", [0.5, 2, 10, 50]),
        ],
        retain_intermediate_calculation_columns=False,
    )


def splink_train(linker):
    """The hand-written training recipe, in one place. See `splink_settings`."""
    from splink import block_on

    linker.training.estimate_probability_two_random_records_match(
        [block_on("name")], recall=0.5)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6)
    # Train on the coordinate rule as well. Blocking EM on `name` alone leaves
    # the name comparison with no variation to learn from, which is what left
    # the first run of this script with an untrained model and a misleading
    # zero.
    for rule in (block_on("round(lat,2)", "round(lon,2)"), block_on("name")):
        try:
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
        except Exception as exc:      # noqa: BLE001
            print(f"    EM on {rule} did not converge: {exc}", flush=True)


def run_splink(records):
    import pandas as pd
    from splink import DuckDBAPI, Linker

    df = pd.DataFrame([{"unique_id": r["id"], "name": r["name"],
                        "lat": r["lat"], "lon": r["lon"]} for r in records])
    linker = Linker(df, splink_settings(), db_api=DuckDBAPI())
    splink_train(linker)
    out = linker.inference.predict(
        threshold_match_probability=0.01).as_pandas_dataframe()
    return [(norm(p), s) for p, s in zip(
        zip(out["unique_id_l"], out["unique_id_r"], strict=False),
        out["match_probability"], strict=False)]


def run_arche(records):
    from arche.resolve import crosswalk

    res = crosswalk(records, records, entity="place", id_field="id")
    return [(norm((e["a_id"], e["b_id"])), e["score"], e["decision"])
            for e in res["matches"] if e["a_id"] != e["b_id"]]


def main() -> int:
    warnings.filterwarnings("ignore")
    if not CSV_PATH.exists():
        print(f"  missing {CSV_PATH}; run data/scripts/stage_nigeria_schools.py")
        return 1

    negatives, positives, filler = build()
    records, neg_ids, pos_ids = _records(negatives, positives, filler)
    seps = sorted(haversine_km(coords(a), coords(b)) for a, b in negatives)
    print(f"  {len(records):,} records: {len(neg_ids)} certain-negative pairs, "
          f"{len(pos_ids)} constructed positives, {len(filler):,} filler")
    print(f"  negatives are {seps[0]:.1f} to {seps[-1]:.0f} km apart, "
          f"median {seps[len(seps)//2]:.0f} km\n", flush=True)

    report = {}

    print("  running splink ...", flush=True)
    sp = run_splink(records)
    print("  running arche ...", flush=True)
    ar = run_arche(records)

    print(f"\n  {'engine / setting':<34}{'true merges':>13}{'FALSE merges':>14}")
    print(f"  {'':<34}{'of 400':>13}{'of 400':>14}")

    for thr in (0.99, 0.95, 0.9, 0.5):
        merged = {p for p, s in sp if s >= thr}
        tp, fp = len(merged & pos_ids), len(merged & neg_ids)
        report[f"splink@{thr}"] = {"true": tp, "false": fp}
        print(f"  {'splink, p >= ' + str(thr):<34}{tp:>13}{fp:>14}")

    auto = {p for p, _, d in ar if d == "match"}
    surf = {p for p, _, d in ar if d in ("match", "review")}
    report["arche_match"] = {"true": len(auto & pos_ids), "false": len(auto & neg_ids)}
    report["arche_surfaced"] = {"true": len(surf & pos_ids),
                                "false": len(surf & neg_ids)}
    print(f"  {'arche, match':<34}{len(auto & pos_ids):>13}{len(auto & neg_ids):>14}")
    print(f"  {'arche, match + review (queued)':<34}{len(surf & pos_ids):>13}"
          f"{len(surf & neg_ids):>14}")

    OUT.write_text(json.dumps({
        "benchmark": "Nigerian school register: names that do not discriminate",
        "negatives": "observed; two schools in different states are not one school",
        "positives": "CONSTRUCTED; one record recorded twice, so recall here is a "
                     "statement about the construction, not about the register",
        "records": len(records), "seed": SEED,
        "splink_version": __import__("splink").__version__,
        "results": report,
    }, indent=2), encoding="utf-8")
    print(f"\n  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
