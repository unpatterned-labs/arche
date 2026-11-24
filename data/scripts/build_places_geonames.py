#!/usr/bin/env python
"""Build the place list the address parser uses, from GeoNames.

The parser uses it to tell whether some words name a town, so it can split
"22 Erinje Road Okitipupa" and read "Dunkwa Atechem" larger to smaller. It
never overrides an address's own order. Written to
``packages/arche-core/src/arche/_data/places_v1.json.gz``.

What goes in:

- **Everywhere:** towns of 5,000 people or more (``cities1000.txt``), and the
  first-level divisions: states, regions, counties, provinces
  (``admin1CodesASCII.txt``).
- **The focus countries** (Nigeria, Kenya, Ghana), from their country files:
  every populated place, the sections of towns GeoNames records (areas like
  Osu or East Legon), the second- and third-level divisions (LGAs,
  sub-counties, districts), and ASCII alternate names.

Each name carries a rank, so a city outranks a village of the same name. Names
that are ordinary address words ("Garage", "Gate", "Camp", "Market") are left
out, since a village called that would otherwise split a landmark.

GeoNames (https://www.geonames.org/) is licensed under CC BY 4.0.

    python data/scripts/build_places_geonames.py ~/.cache/arche-scratch/geonames
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "packages" / "arche-core" / "src" / "arche" / "_data" / "places_v1.json.gz"
FOCUS = ("NG", "KE", "GH")
GLOBAL_MIN_POP = 5000

# Words an address uses for something other than a place. A place with one of
# these as its whole name is left out.
NOT_NAMES = set(str.split("""
road street avenue lane close crescent drive way court square place terrace
gardens grove mews walk parade row highway expressway bypass junction
roundabout bridge market station stop stage garage gate camp park estate
hospital clinic school college university church mosque mission hotel bank
plaza mall centre center house tower building complex office shop farm
quarters village town city new old central north south east west upper
lower layout extension area zone phase block plot line
"""))


def fold(s: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s.casefold()).split())


def rank(fcode: str, pop: int) -> int:
    """6 capital, 5 state seat or 100k+, 4 district seat or 10k+, 3 any
    population, 2 a village, 1 a section of a town (an area)."""
    if fcode == "PPLC":
        return 6
    if fcode == "PPLA" or pop >= 100_000:
        return 5
    if fcode == "PPLA2" or pop >= 10_000:
        return 4
    if fcode in ("PPLA3", "PPLA4") or pop > 0:
        return 3
    if fcode == "PPLX":
        return 1
    return 2


def ascii_names(row: list[str], alternates: bool) -> set[str]:
    names = {row[1], row[2]}
    if alternates:
        names |= {a for a in row[3].split(",") if a}
    return {n for n in names
            if n.isascii() and len(fold(n)) >= 3 and fold(n) not in NOT_NAMES
            and not re.search(r"\d", n)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("geonames", type=Path)
    args = ap.parse_args()
    g = args.geonames.expanduser()
    best: dict[tuple[str, str, str], list] = {}   # (fold, country, kind) -> row

    def add(name: str, cc: str, kind: str, r: int, admin1: str) -> None:
        key = (fold(name), cc, kind)
        if key not in best or r > best[key][3]:
            best[key] = [name, cc, kind, r, admin1]

    for line in (g / "cities1000" / "cities1000.txt").read_text(encoding="utf-8").splitlines():
        row = line.rstrip("\n").split("\t")
        pop = int(row[14] or 0)
        if row[8] in FOCUS or pop < GLOBAL_MIN_POP:
            continue
        for n in ascii_names(row, alternates=False):
            add(n, row[8], "town", rank(row[7], pop), row[10])
    for line in (g / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
        code, name, ascii_name, _ = line.rstrip("\n").split("\t")
        cc = code.split(".")[0]
        for n in {name, ascii_name}:
            if n.isascii() and fold(n) not in NOT_NAMES:
                add(n, cc, "region", 0, code.split(".")[1])
                bare = re.sub(r"(?i)\s+(state|region|county|province)$", "", n)
                if bare != n and fold(bare) not in NOT_NAMES:
                    add(bare, cc, "region", 0, code.split(".")[1])
    for cc in FOCUS:
        for line in (g / cc / f"{cc}.txt").read_text(encoding="utf-8").splitlines():
            row = line.rstrip("\n").split("\t")
            cls, fcode, pop = row[6], row[7], int(row[14] or 0)
            if cls == "P" and fcode not in ("PPLQ", "PPLH", "PPLW", "PPLCH"):
                kind = "area" if fcode == "PPLX" else "town"
                for n in ascii_names(row, alternates=True):
                    add(n, cc, kind, rank(fcode, pop), row[10])
            elif cls == "A" and fcode in ("ADM2", "ADM3"):
                for n in ascii_names(row, alternates=True):
                    add(n, cc, "district", 0, row[10])
    # Stored as a lookup index: folded names, newline-joined, grouped by kind and
    # rank. One string per group loads far faster and smaller than a row each.
    towns: dict[int, set[str]] = {}
    focus: dict[int, set[str]] = {}
    regions: set[str] = set()
    districts: set[str] = set()
    for name, cc, kind, r, _admin1 in best.values():
        key = fold(name)
        if kind in ("town", "area"):
            (focus if cc in FOCUS else towns).setdefault(r, set()).add(key)
        elif kind == "region":
            regions.add(key)
        else:
            districts.add(key)
    sources = {p.name: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [g / "cities1000" / "cities1000.txt", g / "admin1CodesASCII.txt"]
               + [g / cc / f"{cc}.txt" for cc in FOCUS]}
    doc = {"version": 1,
           "source": "GeoNames (https://www.geonames.org/), CC BY 4.0",
           "built_from": sources,
           # Towns of 5,000+ everywhere else, and every place in the focus
           # countries, where the list is full enough that a name it lacks is
           # no town there.
           "towns": {str(r): "\n".join(sorted(v)) for r, v in sorted(towns.items())},
           "focus_countries": list(FOCUS),
           "focus_towns": {str(r): "\n".join(sorted(v)) for r, v in sorted(focus.items())},
           "regions": "\n".join(sorted(regions)),
           "districts": "\n".join(sorted(districts))}
    # mtime=0, so the same sources always give the same bytes (and sha256).
    data = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    with open(OUT, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9,
                                               mtime=0, filename="") as fh:
        fh.write(data)
    print({r: len(v) for r, v in sorted(towns.items())},
          {r: len(v) for r, v in sorted(focus.items())}, "regions", len(regions),
          "districts", len(districts), OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
