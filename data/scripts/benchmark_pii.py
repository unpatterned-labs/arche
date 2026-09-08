#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""The detection benchmark: what each backend finds, misses and invents.

    python data/scripts/benchmark_pii.py                       # basic
    python data/scripts/benchmark_pii.py --backend basic,gliner2-pii
    python data/scripts/benchmark_pii.py --set data/pii_bench/african_context_v0.jsonl --json OUT

Why this exists
---------------
Every detection claim before this file -- "the lexicon finds African names",
"`auto` adds what the rules cannot see" -- had no number behind it, and a
detector without a recall figure is a promise. This runs `Pipeline` over a set
with exact spans and reports, per category and per backend:

* **recall** -- truth spans with an overlapping detection of the same category;
* **precision** -- detections of a category that overlap a truth span of it;
* **false positives** -- detections overlapping no truth span at all, with the
  *negative* they landed on when the set records one (an order number, an
  ISBN, a bare ten-digit reference), which is what the cue-gate audit reads;
* **nested** -- detections overlapping a truth span of another category (a
  LOCATION inside an ADDRESS). Not a false positive; reported so it is not
  mistaken for one.

Overlap, not exact boundaries, because the lexicon emits one span per name
token and the truth is the whole name; the question is whether the person was
found, not whether the boundary matches the annotator's.

The set
-------
`data/pii_bench/african_context_v0.jsonl` is **constructed** (see its
DATACARD): templates over validated identifiers, phones, emails, addresses and
two pools of names. Its numbers say the detectors read what they were built
to read. They are not recall on a clinic's notes, and are labelled
*constructed* wherever published.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

DEFAULT_SET = _REPO / "data" / "pii_bench" / "african_context_v0.jsonl"
RESULT = _REPO / "data" / "pii_bench" / "benchmark_pii_result.json"


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


# ai4privacy's label vocabulary onto arche's categories. Labels arche has no
# category for (USERNAME, TIME, DATE, SEX, TITLE, GEOCOORD) become *unscored*
# spans: a detection over one is nested, not a false positive, and missing one
# is not a miss. Licence note: that set is academic-only, no derivatives; this
# adapter reads a local copy for an unpublished measurement and nothing from
# the set enters the repository (see data/pii_bench/DATACARD.md).
_AI4PRIVACY = {
    "GIVENNAME1": "PII-1-NAME", "GIVENNAME2": "PII-1-NAME",
    "LASTNAME1": "PII-1-NAME", "LASTNAME2": "PII-1-NAME", "LASTNAME3": "PII-1-NAME",
    "EMAIL": "PII-3-EMAIL", "TEL": "PII-3-PHONE",
    "STREET": "PII-4-ADDRESS", "BUILDING": "PII-4-ADDRESS", "SECADDRESS": "PII-4-ADDRESS",
    "CITY": "PII-4-LOCATION", "STATE": "PII-4-LOCATION", "COUNTRY": "PII-4-LOCATION",
    "POSTCODE": "PII-4-LOCATION",
    "BOD": "PII-1-DOB", "IP": "PII-8-IP_ADDRESS", "PASS": "PII-8-PASSWORD",
    "SOCIALNUMBER": "PII-2-NATIONAL_ID", "IDCARD": "PII-2-NATIONAL_ID",
    "PASSPORT": "PII-2-PASSPORT", "DRIVERLICENSE": "PII-2-DRIVERS_LICENCE",
}
_AI4PRIVACY_JURISDICTION = {"English": "GB", "French": "FR", "German": "DE",
                            "Italian": "IT", "Spanish": "ES", "Dutch": "NL"}


def load_rows(path: Path, fmt: str = "arche") -> list[dict]:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if fmt == "arche":
        return lines
    if fmt != "ai4privacy":
        raise ValueError(f"unknown --format {fmt!r}; use arche or ai4privacy")
    rows = []
    for i, raw in enumerate(lines):
        spans, unscored = [], []
        for m in raw.get("privacy_mask", []):
            category = _AI4PRIVACY.get(m["label"])
            entry = {"start": m["start"], "end": m["end"]}
            if category:
                spans.append({**entry, "category": category, "label": m["label"]})
            else:
                unscored.append({**entry, "label": m["label"]})
        rows.append({"id": raw.get("id", str(i)),
                     "jurisdiction": _AI4PRIVACY_JURISDICTION.get(raw.get("language"), "GB"),
                     "text": raw["source_text"], "spans": spans, "negatives": [],
                     "unscored": unscored})
    return rows


def run(rows: list[dict], backend: str) -> dict:
    from arche import Pipeline

    per_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"truth": 0, "hit": 0,
                                                             "predicted": 0, "correct": 0})
    fp_by_negative: dict[str, int] = defaultdict(int)
    fp_by_category: dict[str, int] = defaultdict(int)
    nested = 0
    name_pools: dict[str, dict[str, int]] = defaultdict(lambda: {"truth": 0, "hit": 0})
    by_jurisdiction: dict[str, dict[str, int]] = defaultdict(lambda: {"truth": 0, "hit": 0})
    pipelines: dict[str, Pipeline] = {}
    seconds = 0.0
    model = None

    for row in rows:
        j = row["jurisdiction"]
        pipe = pipelines.setdefault(j, Pipeline(jurisdiction=j, backend=backend))
        t0 = time.perf_counter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = pipe.process(row["text"])
        seconds += time.perf_counter() - t0
        model = model or result.metadata.get("model")
        preds = [(d.start, d.end, d.category) for d in result.detections]
        truth = [(s["start"], s["end"], s["category"], s) for s in row["spans"]]

        for start, end, cat, meta in truth:
            per_cat[cat]["truth"] += 1
            by_jurisdiction[j]["truth"] += 1
            hit = any(_overlaps((start, end), (ps, pe)) and pc == cat for ps, pe, pc in preds)
            if hit:
                per_cat[cat]["hit"] += 1
                by_jurisdiction[j]["hit"] += 1
            if cat == "PII-1-NAME":
                name_pools[meta.get("pool", "?")]["truth"] += 1
                name_pools[meta.get("pool", "?")]["hit"] += int(hit)

        unscored = [(u["start"], u["end"]) for u in row.get("unscored", [])]
        for ps, pe, pc in preds:
            per_cat[pc]["predicted"] += 1
            same = [t for t in truth if t[2] == pc and _overlaps((ps, pe), (t[0], t[1]))]
            other = ([t for t in truth if t[2] != pc and _overlaps((ps, pe), (t[0], t[1]))]
                     or [u for u in unscored if _overlaps((ps, pe), u)])
            if same:
                per_cat[pc]["correct"] += 1
            elif other:
                nested += 1
            else:
                fp_by_category[pc] += 1
                landed = next((n["kind"] for n in row.get("negatives", [])
                               if _overlaps((ps, pe), (n["start"], n["end"]))), "free text")
                fp_by_negative[landed] += 1

    def ratio(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    categories = {
        cat: {**v, "recall": ratio(v["hit"], v["truth"]),
              "precision": ratio(v["correct"], v["predicted"])}
        for cat, v in sorted(per_cat.items())
    }
    truth_total = sum(v["truth"] for v in per_cat.values())
    hit_total = sum(v["hit"] for v in per_cat.values())
    return {
        "backend": backend,
        "model": model,
        "rows": len(rows),
        "seconds_per_text": round(seconds / max(len(rows), 1), 4),
        "recall": ratio(hit_total, truth_total),
        "false_positives": sum(fp_by_category.values()),
        "false_positives_per_100_texts": round(100 * sum(fp_by_category.values()) / len(rows), 2),
        "nested": nested,
        "categories": categories,
        "false_positives_by_category": dict(sorted(fp_by_category.items())),
        "false_positives_landed_on": dict(sorted(fp_by_negative.items())),
        "names_by_pool": {k: {**v, "recall": ratio(v["hit"], v["truth"])}
                          for k, v in sorted(name_pools.items())},
        "by_jurisdiction": {k: {**v, "recall": ratio(v["hit"], v["truth"])}
                            for k, v in sorted(by_jurisdiction.items())},
    }


def _print(report: dict) -> None:
    print(f"{report['backend']:<12} model={report['model']}  rows={report['rows']}  "
          f"{report['seconds_per_text']*1000:.0f} ms/text  recall {report['recall']}  "
          f"false positives {report['false_positives']} "
          f"({report['false_positives_per_100_texts']}/100 texts)  nested {report['nested']}")
    print(f"  {'category':<22} {'truth':>5} {'hit':>4} {'recall':>7} {'pred':>5} {'precision':>9}")
    for cat, v in report["categories"].items():
        rec = "-" if v["recall"] is None else f"{v['recall']:.3f}"
        pre = "-" if v["precision"] is None else f"{v['precision']:.3f}"
        print(f"  {cat:<22} {v['truth']:>5} {v['hit']:>4} {rec:>7} {v['predicted']:>5} {pre:>9}")
    if report["false_positives_landed_on"]:
        print("  false positives landed on:", report["false_positives_landed_on"])
        print("  false positives by category:", report["false_positives_by_category"])
    print("  names by pool:", {k: v["recall"] for k, v in report["names_by_pool"].items()})
    print("  by jurisdiction:", {k: v["recall"] for k, v in report["by_jurisdiction"].items()})


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", default=str(DEFAULT_SET), help="JSONL with text + spans")
    ap.add_argument("--backend", default="basic",
                    help="comma-separated: basic, gliner2-pii, auto")
    ap.add_argument("--json", default=None, help="write the report here (default: the result file)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--format", choices=["arche", "ai4privacy"], default="arche",
                    help="the set's row format (default arche)")
    args = ap.parse_args(argv[1:])

    rows = load_rows(Path(args.set), args.format)
    if args.limit:
        rows = rows[:args.limit]
    if args.format != "arche" and not args.json:
        raise SystemExit("a non-arche set must be written with --json OUT, never to the "
                         "committed result file (licence: see data/pii_bench/DATACARD.md)")
    reports = []
    for backend in [b.strip() for b in args.backend.split(",") if b.strip()]:
        report = run(rows, backend)
        _print(report)
        reports.append(report)

    out = Path(args.json) if args.json else RESULT
    doc = {
        "benchmark": "arche detection benchmark",
        "set": str(Path(args.set).resolve().relative_to(_REPO)) if Path(args.set).resolve().is_relative_to(_REPO) else args.set,
        "set_kind": "constructed",
        "rows": len(rows),
        "spans": sum(len(r["spans"]) for r in rows),
        "negatives": sum(len(r.get("negatives", [])) for r in rows),
        "scoring": "overlap of same category = hit; detection overlapping no truth span = false positive",
        "results": reports,
    }
    if out == RESULT and RESULT.exists():
        previous = json.loads(RESULT.read_text(encoding="utf-8"))
        kept = [r for r in previous.get("results", [])
                if r["backend"] not in {r2["backend"] for r2 in reports}]
        doc["results"] = kept + reports
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
