#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""The organisation lane's first accuracy number, on a public labelled set.

    python datasets/organisations_dataops/bench_organisation.py

What this measures, and what it does not
----------------------------------------
The pass criteria were declared *before* the run, in
`docs/WEEK_PLAN_AGRICULTURE_ARM_20260814.md`:

    1. >= +0.10 F1 over the `person` pack on the same set
    2. >= +0.05 F1 over a token-sort baseline on the same set
    3. no increase in false merges against the untuned baseline

All three are **relative** comparisons on one set, which is the only kind of
claim a set this size can carry. They are not a claim about absolute quality.

The benchmark
-------------
ER_Magellan **Fodors-Zagats** (Structured) — restaurant listings from two
guides, matched by analysts. Businesses with a name, address, city, phone and
cuisine type: the closest thing to organisation-name resolution in a public,
labelled, baselined entity-matching suite.

Why not something better fitting — the honest survey:

* **OpenSanctions Pairs** is the right benchmark and is not usable here.
  755,540 analyst-labelled pairs, 293 sources, 31 countries, organisations and
  persons separately, cross-script names. It is **CC-BY-NC**, and the project
  states plainly that "Businesses must acquire a data license to use the
  dataset." arche is developed alongside a commercial product, so this needs a
  purchased licence — a business decision, not a technical one. It remains the
  single highest-value benchmark upgrade available to this lane.
* **ER_Magellan Company** is in the "Textual" category: company *web-page
  text*, not organisation names. Matching long documents would produce a number
  that says nothing about what a name-based pack does. It is also not present
  in the mirror repo — only a README.
* **Leipzig** sets are vendored here already but are products and bibliographic
  records, not organisations.

Known limits of this set, stated up front because they bound the claim:

* **Small.** 946 labelled pairs across all splits, ~110 positives.
* **Near-saturated.** Published learned baselines report ~100 F1 on it, so it
  discriminates poorly at the top. It can still separate a calibrated pack from
  an uncalibrated one, which is exactly what the three criteria ask.
* **Restaurants, not cooperatives.** It is Anglophone US business listings. It
  says nothing about West African organisation naming, and no number from it
  may be cited as if it did.

Licence
-------
The benchmark data is **fetched, never vendored.** The ER_Magellan datasets are
published for benchmarking, but neither the Magellan data repository nor the
DeepMatcher project states redistribution terms for the data itself (the *code*
is BSD). Unclear terms mean this script downloads to a local cache and the repo
ships the script rather than the data — using a published benchmark to compute
a number is not redistributing it.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

BASE = ("https://raw.githubusercontent.com/megagonlabs/ditto/master/"
        "data/er_magellan/Structured/Fodors-Zagats")
SPLITS = ("train", "valid", "test")
CACHE = Path(__file__).resolve().parent / "fodors_zagats.json.gz"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                       / "packages" / "arche-core" / "src"))


def _parse(cell: str) -> dict:
    """`COL name VAL citrus COL addr VAL ...` -> {"name": "citrus", ...}."""
    out: dict[str, str] = {}
    for chunk in cell.split("COL ")[1:]:
        if " VAL " not in chunk:
            continue
        key, _, val = chunk.partition(" VAL ")
        # The serialisation quotes inconsistently: ` le chardonnay ' and
        # ' 6703 melrose ave. ' both appear. Strip the decoration, keep the text.
        out[key.strip()] = re.sub(r"[`'\"]", " ", val).strip()
    return out


def _load() -> list[tuple[dict, dict, int]]:
    if CACHE.exists():
        with gzip.open(CACHE, "rt", encoding="utf-8") as fh:
            return [(a, b, y) for a, b, y in json.load(fh)]
    rows: list[tuple[dict, dict, int]] = []
    for split in SPLITS:
        req = urllib.request.Request(f"{BASE}/{split}.txt",
                                     headers={"User-Agent": "arche-dataops/0.4"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            rows.append((_parse(parts[0]), _parse(parts[1]), int(parts[2])))
    with gzip.open(CACHE, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return rows


def _to_record(d: dict, rid: str) -> dict:
    """Map the benchmark's columns onto the field names the packs expect."""
    return {"id": rid, "name": d.get("name", ""),
            "address": " ".join(x for x in (d.get("addr"), d.get("city")) if x),
            "phone": d.get("phone", "")}


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.casefold()) if t}


def _token_sort(a: dict, b: dict) -> float:
    """The baseline everyone reaches for first: Jaccard over name tokens."""
    ta, tb = _tokens(a.get("name", "")), _tokens(b.get("name", ""))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _score(rows, mode: str) -> dict:
    from arche.resolve import crosswalk

    tp = fp = fn = 0
    for i, (a, b, y) in enumerate(rows):
        ra, rb = _to_record(a, f"a{i}"), _to_record(b, f"b{i}")
        if mode == "token_sort":
            pred = 1 if _token_sort(a, b) >= 0.5 else 0
        else:
            res = crosswalk([ra], [rb], entity=mode, id_field="id")
            pred = 1 if (res["matches"] and
                         res["matches"][0]["decision"] == "match") else 0
        if pred and y:
            tp += 1
        elif pred and not y:
            fp += 1
        elif not pred and y:
            fn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "true_merges": tp, "false_merges": fp,
            "missed": fn}


def main() -> int:
    rows = _load()
    pos = sum(1 for *_, y in rows if y)
    print(f"ER_Magellan Fodors-Zagats: {len(rows)} labelled pairs, "
          f"{pos} positives ({pos / len(rows):.1%})\n", flush=True)

    results = {}
    for mode, label in (("organisation", "organisation pack"),
                        ("person", "person pack"),
                        ("token_sort", "token-sort baseline")):
        results[mode] = _score(rows, mode)
        r = results[mode]
        print(f"  {label:22s} P={r['precision']:.4f}  R={r['recall']:.4f}  "
              f"F1={r['f1']:.4f}  false merges={r['false_merges']:>3}  "
              f"missed={r['missed']:>3}", flush=True)

    org, per, tok = results["organisation"], results["person"], results["token_sort"]
    print("\n  pre-declared criteria (set before the run):")
    c1 = org["f1"] - per["f1"] >= 0.10
    c2 = org["f1"] - tok["f1"] >= 0.05
    c3 = org["false_merges"] <= tok["false_merges"]
    print(f"    1. >= +0.10 F1 over person pack   : "
          f"{org['f1'] - per['f1']:+.4f}  {'PASS' if c1 else 'FAIL'}")
    print(f"    2. >= +0.05 F1 over token-sort    : "
          f"{org['f1'] - tok['f1']:+.4f}  {'PASS' if c2 else 'FAIL'}")
    print(f"    3. no increase in false merges    : "
          f"{org['false_merges']} vs {tok['false_merges']}  "
          f"{'PASS' if c3 else 'FAIL'}")
    print(f"\n  VERDICT: {'PASS' if (c1 and c2 and c3) else 'FAIL'} "
          f"— published either way, per standing practice.")

    out = Path(__file__).resolve().parent / "bench_organisation_result.json"
    out.write_text(json.dumps(
        {"benchmark": "ER_Magellan Fodors-Zagats (Structured)",
         "pairs": len(rows), "positives": pos, "results": results,
         "criteria": {"f1_over_person": c1, "f1_over_token_sort": c2,
                      "no_extra_false_merges": c3},
         "verdict": "PASS" if (c1 and c2 and c3) else "FAIL"},
        indent=2), encoding="utf-8")
    print(f"  -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
