# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Does a shipped population prior transfer to a population it was not built on?

    uv run python datasets/places_dataops/bench_prior_transfer.py

`bench_population_vs_batch.py` showed that arche's shipped place table gives
**batch invariance**: its false-merge count does not move when the caller's
batch shrinks, where Splink's rises from 2 to 368. That result is real and it is
only half a claim. Invariance is worth nothing if the fixed answer is wrong, and
a stable wrong answer is worse than an unstable one because nothing signals it.

So this asks the other half: **is the shipped prior CALIBRATED off-distribution,
or merely constant?**

The table's own provenance names the twenty countries it was built from -- GB,
IE, and eighteen African, South Asian and Latin American strata. France, Italy,
Spain and Portugal are not among them, which makes them a clean out-of-sample
population of the *same entity type*: place names, from the same source, in the
same format.

The failure mode to look for is specific and is visible before any pair is
scored. Distinctiveness under the shipped table::

    school   0.345  ordinary        mairie   0.860  DISTINCTIVE
    hospital 0.351  ordinary        eglise   1.000  DISTINCTIVE
    health   0.312  ordinary        moulin   1.000  DISTINCTIVE
    centre   0.411  ordinary        ferme    1.000  DISTINCTIVE

`Moulin`, `Ferme` and `Église` are among the commonest elements in French place
names -- Mill, Farm, Church. A table that has never seen them scores them as
maximally rare, so two unrelated hamlets sharing one clear the distinctive gate
and merge. **The prior is not uninformative off-distribution; it is inverted.**

Three arms, on identical pairs:

    shipped         the population table, as it ships
    self            estimated from the batch, which is what Splink does
    blend           shipped, but any token the batch says is common is demoted

Negatives are observed and certain: two places of the same name in different
first-level administrative regions are not one place. Positives are constructed
-- one record written twice with an ordinary variation -- so the true-merge
column measures the construction, not the register. Read the columns together.

Licence: GeoNames, CC-BY 4.0, the same source and licence as twenty of the
strata already inside the shipped table.
"""
from __future__ import annotations

import collections
import csv
import io
import json
import random
import sys
import urllib.request
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

CACHE = _REPO / "data" / "_cache" / "geonames"
OUT = _HERE / "bench_prior_transfer_result.json"
SEED = 20260824
PAIRS = 300
POSITIVES = 300
FILLER = 4000

#: `NG` is inside the shipped table; `FR` and `IT` are not. Same source, same
#: format, same construction -- only the distribution changes.
COUNTRIES = (("NG", "in-distribution"), ("FR", "OUT of distribution"),
             ("IT", "OUT of distribution"))

#: GeoNames feature classes for populated places and spots/buildings. Anything
#: else is terrain, and terrain names do not behave like facility names.
KEEP_CLASSES = {"P", "S"}


def fetch(cc: str) -> list[dict]:
    """GeoNames rows for one country, cached after the first run."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{cc}.tsv"
    if not cached.exists():
        url = f"https://download.geonames.org/export/dump/{cc}.zip"
        print(f"  fetching {url}", flush=True)
        with urllib.request.urlopen(url, timeout=180) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            cached.write_bytes(zf.read(f"{cc}.txt"))
    rows = []
    with cached.open(encoding="utf-8", newline="") as fh:
        for parts in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(parts) < 11:
                continue
            name, fclass, admin1 = parts[1].strip(), parts[6], parts[10].strip()
            if not (name and admin1 and fclass in KEEP_CLASSES):
                continue
            try:
                lat, lon = float(parts[4]), float(parts[5])
            except ValueError:
                continue
            rows.append({"name": name, "admin1": admin1, "lat": lat, "lon": lon})
    return rows


def build(rows: list[dict]):
    """Observed negatives and constructed positives, as in the school bench."""
    by_name = collections.defaultdict(list)
    for r in rows:
        by_name[r["name"].casefold()].append(r)

    rng = random.Random(SEED)
    pool = sorted(n for n, rs in by_name.items()
                  if len({x["admin1"] for x in rs}) > 1)
    rng.shuffle(pool)

    negatives = []
    for n in pool[: PAIRS * 3]:
        rs = by_name[n]
        a = rs[0]
        b = next((x for x in rs if x["admin1"] != a["admin1"]), None)
        if b:
            negatives.append((a, b))
        if len(negatives) >= PAIRS:
            break

    singles = [rs[0] for n, rs in sorted(by_name.items()) if len(rs) == 1]
    rng.shuffle(singles)
    positives = []
    for k, r in enumerate(singles[: POSITIVES * 2]):
        words = r["name"].split()
        if len(words) < 2:
            continue
        # An ordinary recording difference: the leading article or type word is
        # dropped, or the name is written without its hyphen.
        alt = (" ".join(words[1:]) if k % 2 == 0
               else r["name"].replace("-", " "))
        if alt.strip().casefold() == r["name"].casefold() or not alt.strip():
            continue
        positives.append((r, alt))
        if len(positives) >= POSITIVES:
            break

    others = [r for r in rows if r["name"]]
    rng.shuffle(others)
    return negatives, positives, others[:FILLER]


def records(negatives, positives, filler):
    out, neg_ids, pos_ids = [], [], []
    for i, (a, b) in enumerate(negatives):
        out.append({"id": f"neg{i}a", "name": a["name"],
                    "lat": a["lat"], "lon": a["lon"]})
        out.append({"id": f"neg{i}b", "name": b["name"],
                    "lat": b["lat"], "lon": b["lon"]})
        neg_ids.append((f"neg{i}a", f"neg{i}b"))
    for i, (r, alt) in enumerate(positives):
        out.append({"id": f"pos{i}a", "name": r["name"],
                    "lat": r["lat"], "lon": r["lon"]})
        out.append({"id": f"pos{i}b", "name": alt,
                    "lat": r["lat"] + 0.0009, "lon": r["lon"] + 0.0009})
        pos_ids.append((f"pos{i}a", f"pos{i}b"))
    for j, r in enumerate(filler):
        out.append({"id": f"fill{j}", "name": r["name"],
                    "lat": r["lat"], "lon": r["lon"]})
    return out, set(neg_ids), set(pos_ids)


def norm(p):
    a, b = p
    return (a, b) if a <= b else (b, a)


#: NAME ONLY. The `place` pack declares `veto_km: 10`, and two places of the
#: same name in different regions are hundreds of kilometres apart -- so the
#: geographic veto refutes every negative before the frequency prior is ever
#: consulted. A first version of this benchmark used the full pack and produced
#: 0-2 false merges in every arm and every country, which reads as "the prior
#: transfers fine" and actually means "the prior was never asked".
#:
#: The question here is whether the prior is calibrated off-distribution, so the
#: name has to be the only evidence. This is not how the pack ships and is not
#: meant to be; it is how you isolate one comparator.
NAME_ONLY = [
    {"field": "name", "kind": "placename", "weight": 2.0},
    {"field": "name", "kind": "tftoken", "weight": 2.0},
]


def run(recs, tf):
    from arche.resolve import reconcile

    edges = reconcile(recs, recs, NAME_ONLY, tf=tf, id_field="id",
                      threshold=0.7)["matches"]
    return [(norm((e["a_id"], e["b_id"])), e["decision"])
            for e in edges if e["a_id"] != e["b_id"]]


def blended(shipped, batch):
    """Shipped counts, with any token the batch finds common demoted.

    The shrinkage arm. It keeps the shipped table's knowledge of everything it
    has seen and lets the caller's own data veto a token the table wrongly
    believes is rare -- which is the whole failure being measured.
    """
    from arche.resolve import TokenFrequencyTable

    counts = dict(shipped._as_counts())                      # noqa: SLF001
    batch_counts = batch._as_counts()                        # noqa: SLF001
    batch_total = sum(batch_counts.values()) or 1
    shipped_total = sum(counts.values()) or 1
    for token, n in batch_counts.items():
        rate = n / batch_total
        if rate >= 1e-3:            # the batch says this is an ordinary word
            counts[token] = max(counts.get(token, 0.0), rate * shipped_total)
    return TokenFrequencyTable.from_counts(counts)


def main() -> int:
    from arche.resolve import TokenFrequencyTable

    results = {}
    print(f"\n  {'country':>9}{'arm':>10}{'true/300':>10}{'FALSE/300':>11}",
          flush=True)
    print("  " + "-" * 40, flush=True)

    for cc, label in COUNTRIES:
        rows = fetch(cc)
        negatives, positives, filler = build(rows)
        recs, neg_ids, pos_ids = records(negatives, positives, filler)
        shipped = TokenFrequencyTable.default("place")
        batch = TokenFrequencyTable.from_corpus([r["name"] for r in recs])
        arms = {"shipped": shipped, "self": batch,
                "blend": blended(shipped, batch)}
        results[cc] = {"label": label, "records": len(recs),
                       "negatives": len(negatives), "positives": len(positives)}
        for arm, tf in arms.items():
            pairs = run(recs, tf)
            asserted = {p for p, d in pairs if d == "match"}
            row = {"true": len(asserted & pos_ids),
                   "false": len(asserted & neg_ids)}
            results[cc][arm] = row
            print(f"  {cc + ' ' + label[:3]:>9}{arm:>10}"
                  f"{row['true']:>10}{row['false']:>11}", flush=True)
        print(flush=True)

    OUT.write_text(json.dumps({
        "benchmark": "does a shipped population prior transfer off-distribution",
        "source": "GeoNames, CC-BY 4.0",
        "in_distribution": "NG is one of the twenty strata inside the shipped "
                           "place table",
        "out_of_distribution": "FR and IT are not in it",
        "negatives": "observed; same name in different admin1 regions",
        "positives": "CONSTRUCTED; one record written twice",
        "seed": SEED,
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"  wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
