#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Does the ledger build the right entities?

    python data/scripts/benchmark_entity_formation.py            # both sets
    python data/scripts/benchmark_entity_formation.py febrl       # one set
    python data/scripts/benchmark_entity_formation.py dblp-acm

Every published arche number scores *pairs*. The ledger does something no
pairwise score measures: it takes the ``match`` edges and unions them into
entities, so A~B and B~C put A, B and C in one entity whether or not A and C
were ever compared. That is how a resolution system quietly merges two
different things, and until this script nothing in the repository counted it.

Two complete-truth sets, run through ``reconcile(store=ledger)`` with exactly
the configuration the benchmark page reports for each:

* **Febrl 4**, name + address, identifier withheld (``bench_febrl.py``). Truth
  clusters: ``rec-N-org`` and ``rec-N-dup-0`` share the entity number ``N``.
* **DBLP-ACM**, hand-declared bibliographic comparators, ``year`` as a
  refuting field (``benchmark_leipzig.py``). Truth clusters: each pair in the
  perfect mapping; both sources are clean, so no true entity has more than
  one record from either side.

For every entity the ledger built, count the distinct truth clusters its
records belong to. One is a correct entity. More than one is a **cross-cluster
merge**: the entity-level false merge, which is worse than a pairwise one
because it propagates. ``held`` says whether the entity is a clique
(``direct``) or depends on a chain (``transitive``); the hypothesis this
script tests is that cross-cluster merges concentrate in the transitive ones.

Published whichever way it falls. Result file lands beside the script's data.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
sys.path.insert(0, str(_REPO / "datasets" / "names_dataops"))

OUT = _REPO / "data" / "er_bench" / "benchmark_entity_formation_result.json"


# --------------------------------------------------------------------------- Febrl


def _febrl() -> tuple[list[dict], list[dict], dict[str, str], dict]:
    """Records, and record id -> truth cluster, exactly as bench_febrl builds them."""
    import bench_febrl  # datasets/names_dataops

    a_rows, b_rows = (list(bench_febrl._fetch(f)) for f in bench_febrl.FILES)
    list_a = [bench_febrl._record(r, with_id=False) for r in a_rows]
    list_b = [bench_febrl._record(r, with_id=False) for r in b_rows]
    truth = {r["id"]: bench_febrl._truth_key(r["id"]) for r in [*list_a, *list_b]}
    call = {"entity": "person", "id_field": "id"}
    return list_a, list_b, truth, call


# --------------------------------------------------------------------------- DBLP-ACM


def _dblp_acm() -> tuple[list[dict], list[dict], dict[str, str], dict]:
    data = _REPO / "data" / "er_bench"

    def read(name: str) -> list[dict]:
        with open(data / name, encoding="utf-8-sig", errors="replace", newline="") as fh:
            return list(csv.DictReader(fh))

    dblp, acm = read("DBLP2.csv"), read("ACM.csv")
    fields = ("title", "authors", "year")
    # Prefix the ids: the two sources' id spaces overlap in shape, and the
    # ledger keys records by content anyway, but the truth map must not.
    list_a = [{"id": f"dblp:{r['id']}", **{f: r[f] for f in fields}} for r in dblp]
    list_b = [{"id": f"acm:{r['id']}", **{f: r[f] for f in fields}} for r in acm]
    truth: dict[str, str] = {}
    for row in read("DBLP-ACM_perfectMapping.csv"):
        cluster = f"pair:{row['idDBLP']}:{row['idACM']}"
        truth[f"dblp:{row['idDBLP']}"] = cluster
        truth[f"acm:{row['idACM']}"] = cluster
    for rec in [*list_a, *list_b]:          # unmatched records are their own cluster
        truth.setdefault(rec["id"], f"single:{rec['id']}")
    comparators = [
        {"field": "title", "kind": "name", "weight": 3.0},
        {"field": "title", "kind": "tftoken", "weight": 2.0},
        {"field": "authors", "kind": "name", "weight": 2.0},
        {"field": "year", "kind": "date", "weight": 0.5, "refutes_below": 0.99},
    ]
    call = {"comparators": comparators, "id_field": "id"}
    return list_a, list_b, truth, call


# --------------------------------------------------------------------------- measure


def measure(name: str, list_a: list[dict], list_b: list[dict],
            truth: dict[str, str], call: dict) -> dict:
    import arche

    ledger = arche.attach("duckdb:///:memory:")
    t0 = time.perf_counter()
    result = arche.reconcile(list_a, list_b, store=ledger, **call)
    t_reconcile = time.perf_counter() - t0

    # Pairwise, for the cross-check against the published numbers.
    true_pairs = {
        (a["id"], b["id"]) for a in list_a for b in list_b
        if truth[a["id"]] == truth[b["id"]]
    }
    matched = {(e["a_id"], e["b_id"]) for e in result["matches"] if e["decision"] == "match"}
    pair_tp = len(matched & true_pairs)
    pair_fp = len(matched - true_pairs)

    # Entity-level.
    t0 = time.perf_counter()
    entities = ledger.entities()
    t_entities = time.perf_counter() - t0
    size = Counter()
    held = Counter()
    cross: list[dict] = []
    records_in_cross = 0
    for view in entities:
        clusters = Counter(truth[r.caller_id] for r in view.records)
        size[len(view.records)] += 1
        held[view.held_together_by] += 1
        if len(clusters) > 1:
            records_in_cross += len(view.records)
            cross.append({
                "entity_id": view.entity_id,
                "records": len(view.records),
                "clusters": len(clusters),
                "held": view.held_together_by,
                "linked_by": len(view.decision_ids),
                "sample": [r.caller_id for r in view.records][:6],
            })
    cross_held = Counter(c["held"] for c in cross)
    ledger.close()

    # How many true clusters of size >1 ended up whole in one pure entity?
    truth_sizes = Counter(truth.values())
    multi = {c for c, n in truth_sizes.items() if n > 1}
    whole = 0
    for view in entities:
        clusters = {truth[r.caller_id] for r in view.records}
        if len(clusters) == 1:
            (cluster,) = clusters
            if cluster in multi and len(view.records) == truth_sizes[cluster]:
                whole += 1

    report = {
        "records": len(list_a) + len(list_b),
        "true_clusters_of_size_gt_1": len(multi),
        "pairs": {
            "true": len(true_pairs), "matched_true": pair_tp, "matched_false": pair_fp,
            "precision": round(pair_tp / (pair_tp + pair_fp), 4) if pair_tp + pair_fp else None,
        },
        "entities": {
            "built": len(entities),
            "by_size": dict(sorted(size.items())),
            "held": dict(held),
            "true_clusters_recovered_whole": whole,
            "recovered_whole_rate": round(whole / len(multi), 4) if multi else None,
            "cross_cluster": len(cross),
            "cross_cluster_rate": round(len(cross) / len(entities), 4) if entities else None,
            "records_in_cross_cluster_entities": records_in_cross,
            "cross_cluster_by_held": dict(cross_held),
            "largest_cross_cluster": max((c["records"] for c in cross), default=0),
        },
        "cross_cluster_examples": sorted(cross, key=lambda c: -c["records"])[:10],
        "seconds": {"reconcile_with_store": round(t_reconcile, 1),
                    "entities": round(t_entities, 1)},
    }
    print(f"\n{name}: {report['records']:,} records, "
          f"{len(true_pairs):,} true pairs, {len(multi):,} true clusters")
    print(f"  pairs     : {pair_tp} true merges, {pair_fp} false merges "
          f"(precision {report['pairs']['precision']})")
    e = report["entities"]
    print(f"  entities  : {e['built']:,} built; sizes {e['by_size']}; held {e['held']}")
    print(f"  recovered : {whole:,} of {len(multi):,} true clusters whole "
          f"({e['recovered_whole_rate']})")
    print(f"  CROSS     : {e['cross_cluster']} entities span >1 truth cluster "
          f"({e['cross_cluster_rate']}), {records_in_cross} records inside them, "
          f"by held {dict(cross_held)}, largest {e['largest_cross_cluster']}")
    for c in report["cross_cluster_examples"][:5]:
        print(f"      {c['records']} records / {c['clusters']} clusters / {c['held']}: "
              f"{c['sample']}")
    print(f"  time      : reconcile+store {t_reconcile:.1f}s, entities {t_entities:.1f}s")
    return report


def main(argv: list[str]) -> int:
    which = set(argv[1:]) or {"febrl", "dblp-acm"}
    results: dict[str, dict] = {}
    if OUT.exists():
        results = json.loads(OUT.read_text(encoding="utf-8")).get("results", {})
    if "febrl" in which:
        results["febrl4_name_address"] = measure("Febrl 4 (name + address)", *_febrl())
    if "dblp-acm" in which:
        results["dblp_acm_year_refutes"] = measure("DBLP-ACM (year refutes)", *_dblp_acm())
    OUT.write_text(json.dumps({
        "benchmark": "entity formation: cross-cluster merges in ledger entities",
        "method": "reconcile(store=ledger) with the published configuration; each entity's "
                  "records mapped to complete-truth clusters; >1 cluster = cross-cluster merge",
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\n-> {OUT.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
