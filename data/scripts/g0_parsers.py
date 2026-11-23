#!/usr/bin/env python
"""G0: how well do arche's address parser and libpostal split an address into parts?

The span is given: each arm receives one whole address string and returns its
components. Two arms:

* ``arche``: ``arche.addr.parse.parse_address`` (no parse counts as every field empty).
* ``libpostal``: libpostal with Senzing's v1.2 parser model, through the ``postal``
  Python binding. Optional: absent until the C library is built.

G0a, the test here, is Senzing's labelled test set (libpostal-data
``files/tests/v1.2.0/test_data.csv``, 12,868 addresses, Apache-2.0), scored on the
countries in arche's scope that it holds: US, GB, AU and ZA. It is libpostal's
vendor test set, so libpostal plays at home; the set holds no NG, GH or KE
address. Those come from G0b, a blind African pack, pre-registered separately.

Fields compared: house_number, road, unit, suburb, city, state, postcode. A value
matches when both sides are equal after case folding and removing punctuation and
spacing. A field the gold leaves empty must be empty in the prediction. An
address parses correctly when every field matches. Only aggregates are written.

    python data/scripts/g0_parsers.py --test <test_data.csv> --arms arche --out <json>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

FIELDS = ("house_number", "road", "unit", "suburb", "city", "state", "postcode")
COUNTRIES = ("us", "gb", "au", "za")
PREREG = REPO / "data" / "er_bench" / "benchmark_g0_parsers_preregistration.json"
BOOT, BOOT_SEED = 10000, 0


def norm(v: str | None) -> str:
    return re.sub(r"[\W_]+", "", (v or "").casefold())


def arche_arm():
    from arche.addr.parse import parse_address

    def parse(text: str) -> dict[str, str]:
        a = parse_address(text)
        if a is None:
            return {}
        c = a.components
        number = c.street_number or (re.sub(r"(?i)^plot\s*", "", c.plot) if c.plot else None)
        return {"house_number": number, "road": c.street, "unit": None,
                "suburb": c.neighborhood or c.area, "city": c.city, "state": c.region,
                "postcode": c.postal_code}
    return parse


def libpostal_arm():
    from postal.parser import parse_address  # needs the C library and LIBPOSTAL_DATA_DIR

    def parse(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for value, label in parse_address(text):
            key = {"house_number": "house_number", "road": "road", "unit": "unit",
                   "suburb": "suburb", "city": "city", "state": "state",
                   "postcode": "postcode"}.get(label)
            if key:
                out[key] = f"{out[key]} {value}" if key in out else value
        return out
    return parse


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - s) / (1 + z * z / n), 4), round((c + s) / (1 + z * z / n), 4)]


def score(rows: list[dict], preds: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {"addresses": len(rows), "fields": {}}
    ok = [all(norm(p.get(f)) == norm(r[f]) for f in FIELDS) for r, p in zip(rows, preds)]
    out["parse_correct"] = sum(ok)
    out["parse_correct_rate"] = round(sum(ok) / len(rows), 4) if rows else None
    out["parse_correct_wilson95"] = wilson(sum(ok), len(rows))
    for f in FIELDS:
        present = [i for i, r in enumerate(rows) if norm(r[f])]
        absent = [i for i, r in enumerate(rows) if not norm(r[f])]
        hit = sum(norm(preds[i].get(f)) == norm(rows[i][f]) for i in present)
        spurious = sum(bool(norm(preds[i].get(f))) for i in absent)
        out["fields"][f] = {"gold_present": len(present), "exact": hit,
                            "recall": round(hit / len(present), 4) if present else None,
                            "spurious": spurious}
    return out, ok


def paired_diff(a: list[bool], b: list[bool]) -> dict[str, float]:
    rng = random.Random(BOOT_SEED)
    n = len(a)
    d = [int(x) - int(y) for x, y in zip(a, b)]
    stats = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    return {"diff": round(sum(d) / n, 4),
            "bootstrap95": [round(stats[int(0.025 * BOOT)], 4), round(stats[int(0.975 * BOOT)], 4)]}


def sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test", type=Path, required=True)
    ap.add_argument("--arms", default="arche,libpostal")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    started = time.time()
    prereg = json.loads(PREREG.read_text(encoding="utf-8")) if PREREG.exists() else None
    if prereg is None:
        raise SystemExit("no preregistration; refusing to score")
    if sha(args.test) != prereg["test"]["sha256"]:
        raise SystemExit("the test file differs from the preregistered one")
    if sha(Path(__file__)) != prereg["code"]["g0_parsers.py"]:
        raise SystemExit("this script changed since the preregistration")
    with args.test.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["country_code"] in COUNTRIES]
    arms = {"arche": arche_arm, "libpostal": libpostal_arm}
    result: dict[str, Any] = {"schema": "arche.g0_parsers.v1",
                              "preregistration_sha256": sha(PREREG),
                              "test_sha256": sha(args.test), "arms": {}}
    correct: dict[str, list[bool]] = {}
    for name in args.arms.split(","):
        parse = arms[name]()
        preds = [parse(r["full_address"]) for r in rows]
        arm: dict[str, Any] = {}
        all_score, ok = score(rows, preds)
        arm["all"] = all_score
        for c in COUNTRIES:
            ix = [i for i, r in enumerate(rows) if r["country_code"] == c]
            arm[c], _ = score([rows[i] for i in ix], [preds[i] for i in ix])
        result["arms"][name] = arm
        correct[name] = ok
        print(name, json.dumps({k: (v["parse_correct_rate"], v["parse_correct_wilson95"])
                                for k, v in arm.items()}), flush=True)
    if {"arche", "libpostal"} <= correct.keys():
        result["libpostal_minus_arche"] = {}
        for c in (*COUNTRIES, "all"):
            ix = range(len(rows)) if c == "all" else [i for i, r in enumerate(rows)
                                                       if r["country_code"] == c]
            ix = list(ix)
            result["libpostal_minus_arche"][c] = paired_diff([correct["libpostal"][i] for i in ix],
                                                             [correct["arche"][i] for i in ix])
        result["verdict"] = {c: ("libpostal" if d["bootstrap95"][0] > 0 else
                                 "arche" if d["bootstrap95"][1] < 0 else "no_difference")
                             for c, d in result["libpostal_minus_arche"].items()}
        print(json.dumps(result["verdict"]))
    result["seconds"] = round(time.time() - started, 1)
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
