#!/usr/bin/env python
"""Score the address parsers on the parser dev pack, and list what arche gets wrong.

The dev pack (``build_parser_dev_pack.py``) is where parser changes are made and
checked; its labels may be read. Fields, matching and the three arms are G0b's
(``g0b_parsers.py``), with one change to arche's mapping: its ``unit`` is
passed through (G0a's mapping always left it empty), and when the street
parser finds nothing the unit is still taken from ``extract_unit``, as the
resolver takes a landmark from ``extract_anchor``. With no street at all, the
places come from ``parse_locality``.

``--pelias`` adds pelias/parser (MIT, rule-based; npm ``pelias-parser``) as a
fourth arm, run in Node by ``pelias_batch.js`` from ``PELIAS_PARSER`` (the
package directory). Its best solution is mapped: housenumber, street, unit
(with its unit type), locality as city, region as state, postcode. It has no
suburb label, so it is scored as leaving suburb empty; a venue is a landmark
and is not scored.

    LIBPOSTAL_DATA_DIR=... uv run --package arche-core --with postal python \\
        data/scripts/parser_dev_eval.py [--errors FIELD] [--no-libpostal]
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("g0b_parsers", HERE / "g0b_parsers.py")
g0b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g0b)

LABELS = g0b.G0B / "dev" / "labels.csv"


def arche_arm():
    from arche.addr import extract_unit, parse_address, parse_locality

    def parse(text: str) -> dict[str, str | None]:
        a = parse_address(text)
        c = a.components if a is not None else parse_locality(text)
        if c is None:
            return {"unit": extract_unit(text)}
        if a is not None and not (c.city or c.neighborhood or c.area):
            # A street (or a landmark) but no place after it: "Mirema along
            # Mirema Drive". The places come from parse_locality.
            p = parse_locality(text)
            if p is not None:
                c.city, c.neighborhood, c.area = p.city, p.neighborhood, p.area
        number = c.street_number or (re.sub(r"(?i)^plot\s*", "", c.plot) if c.plot else None)
        return {"house_number": number, "road": c.street, "unit": c.unit or extract_unit(text),
                "suburb": c.neighborhood or c.area, "city": c.city, "state": c.region,
                "postcode": c.postal_code}
    return parse


def pelias_arm(texts: list[str]):
    """pelias/parser over every text at once; returns a lookup by text."""
    done = subprocess.run(
        ["node", str(HERE / "pelias_batch.js")], input=json.dumps(texts),
        capture_output=True, text=True, check=True,
        env={**os.environ, "PELIAS_PARSER": os.environ["PELIAS_PARSER"]})
    keys = {"housenumber": "house_number", "street": "road", "unit_type": "unit",
            "unit": "unit", "locality": "city", "region": "state", "postcode": "postcode"}
    table = {}
    for text, pairs in zip(texts, json.loads(done.stdout)):
        out: dict[str, str] = {}
        for c in sorted(pairs, key=lambda c: c["start"]):
            if c["label"] in keys:
                f = keys[c["label"]]
                out[f] = f"{out[f]} {c['value']}" if f in out else c["value"]
        table[text] = out
    return lambda t: table[t]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--errors", help="list arche_cased's misses on this field")
    ap.add_argument("--no-libpostal", action="store_true")
    ap.add_argument("--pelias", action="store_true", help="add pelias/parser (needs PELIAS_PARSER)")
    ap.add_argument("--places", action="store_true",
                    help="register the place list built from the lists (build_places_from_lists.py)")
    args = ap.parse_args()
    if args.places:
        from arche.addr.places import register_places
        print("registered", register_places(g0b.G0B / "places_from_lists.json"), "places")
    with LABELS.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if not (r.get("skip") or "").strip()]
    arche = arche_arm()
    arms = {"arche": arche, "arche_cased": lambda t: arche(g0b.recase(t))}
    # Without libpostal, arche_cased stands in for it so the paired comparisons run.
    arms["libpostal"] = arms["arche_cased"] if args.no_libpostal else g0b.g0.libpostal_arm()
    if args.pelias:
        arms["pelias"] = pelias_arm([r["address"] for r in rows])
    out = g0b.run(rows, arms, "country")
    for a, v in out["arms"].items():
        print(a, json.dumps({c: x["parse_correct_rate"] for c, x in v.items()}))
        print("   exact/gold/spurious", json.dumps(
            {f: [x["exact"], x["gold_present"], x["spurious"]]
             for f, x in v["all"]["fields"].items()}))
    norm = g0b.g0.norm
    kinds: Counter = Counter()
    for r in rows:
        gold = g0b.tidy(r)
        got = g0b.tidy(arms["arche_cased"](r["address"]) or {})
        for f in g0b.FIELDS:
            if norm(gold[f]) != norm(got[f]):
                kinds[(f, "missed" if not got[f] else "spurious" if not gold[f]
                       else "wrong")] += 1
                if f == args.errors:
                    print(f"  {r['address'][:70]!r:74} gold={gold[f]!r} got={got[f]!r}")
    print("arche_cased misses:", ", ".join(f"{f} {k} {n}" for (f, k), n in kinds.most_common()))


if __name__ == "__main__":
    main()
