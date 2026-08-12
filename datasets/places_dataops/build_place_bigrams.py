# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build a PLACE **bigram** frequency table — prototype, not shipped.

Why
---
The distinctiveness gate asks whether two names share something *rare*, and it
asks that of **tokens**. That works where the identifying part of a name is one
rare word: ``Karfi Health Post`` clears on ``karfi`` at 0.93.

It fails where identity lives in a *phrase* built from ordinary words. Every
token of ``London Bridge Hospital`` is common — ``london`` 0.69, ``bridge``
0.61, ``hospital`` 0.35 — so two records of that hospital, 30 m apart with
byte-identical names, are routed to ``review``. Measured on the London
benchmark: 12 of 86 labelled true pairs abstained for this reason.

A bigram table separates the two cases without any curation, because the corpus
already knows the difference:

    general hospital   0.485      london bridge  0.919
    primary health     0.322      kings college  0.966
    health post        0.349      king george    0.949

Status
------
**Prototype.** The output is written to the cache, not into the wheel, and
nothing in ``arche`` reads it. Before this could ship it needs: a
population-scale guard so a small corpus cannot clear the gate on noise;
per-region evidence so a reviewer can see which phrase cleared it; a decision on
part-of pairs (``King's College Hospital Emergency Department`` against
``King's College Hospital`` is a granularity error that phrase rarity makes
*easier* to trip); and tests.

Corpus
------
The same strata and the same equal-mass weighting as
``build_place_frequencies.py``, read from that script's cache so this does not
re-fetch. Run the token builder first if the cache is cold.

Usage
-----
    python datasets/places_dataops/build_place_bigrams.py
    python datasets/places_dataops/build_place_bigrams.py --prune-min 5
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
from arche.resolve._tokenfreq import (  # noqa: E402
    TOKEN_RULES,
    TokenFrequencyTable,
    _phrase_tokens,
    _tokens as _raw_tokens,
)

# Bound to the CLI rule in main(). The bigram table MUST be built under the
# same tokenisation as the unigram table it accompanies: a phrase assembled
# from one tokenisation and looked up in counts accumulated under another is
# the same silent mismatch the `token_rule` machinery exists to prevent.
_TOKEN_RULE = "plain"


def _tokens(text):
    return _raw_tokens(text, _TOKEN_RULE)

_CACHE = _REPO / "datasets" / "data" / "_cache" / "places"
_OUT = (
    _REPO / "packages" / "arche-core" / "src" / "arche" / "resolve" / "_data"
    / "place_bigrams.json.gz"
)

_GN_NAME, _GN_ASCII, _GN_FCLASS, _GN_FCODE = 1, 2, 6, 7
_HEALTH = {"HSP", "HSPC", "HSPD", "HSPL"}
_ENERGY = {"PS", "PSH", "PSTN"}
_EDU = {"SCH", "SCHA", "SCHC", "SCHL", "SCHM", "SCHN", "SCHT", "UNIV"}
_CIVIC = {"BLDG", "MKT", "MFG", "MFGB", "MFGPH", "AIRP", "RSTN", "BANK", "COURT",
          "GOVL", "HTL", "LIBR", "MUS", "PO", "POL", "PRN", "REST", "STDM",
          "STNB", "TRIG", "WTRW", "CMTY", "CH", "MSQE", "TMPL"}
_CODES = _HEALTH | _ENERGY | _EDU | _CIVIC

_LOCAL = [
    ("grid3", "data/GRID3_NGA_health_facilities_v2.csv", ("facility_name",)),
    ("hfr-kano", "data/hfr_kano.csv", ("name", "alternate_name")),
    ("hfr-edo", "data/hfr_edo.csv", ("name", "alternate_name")),
    ("hfr-ondo", "data/hfr_ondo.csv", ("name", "alternate_name")),
]


def bigrams(text: str) -> list[str]:
    # The runtime's phrase reading, not the unigram one: the possessive is
    # FOLDED so adjacency is a property of the name. Building with the append
    # reading put phantom pairs like "hospital kings" in the table, which were
    # rare precisely because they never occur.
    toks = _phrase_tokens(text or "", _TOKEN_RULE)
    return [" ".join(toks[i:i + 2]) for i in range(len(toks) - 1)]


def _geonames(path: Path) -> Counter[str]:
    cc = path.stem
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(path) as zf, zf.open(f"{cc}.txt") as fh:
        for raw in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
            col = raw.rstrip("\n").split("\t")
            if len(col) <= _GN_FCODE:
                continue
            if col[_GN_FCLASS] == "P" or (
                col[_GN_FCLASS] == "S" and col[_GN_FCODE] in _CODES
            ):
                counts.update(bigrams(col[_GN_NAME]))
                if col[_GN_ASCII] and col[_GN_ASCII] != col[_GN_NAME]:
                    counts.update(bigrams(col[_GN_ASCII]))
    return counts


def _csv(path: Path, fields: tuple[str, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        for rec in csv.DictReader(fh):
            for f in fields:
                counts.update(bigrams(rec.get(f) or ""))
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--token-rule", default="possessive", choices=list(TOKEN_RULES),
                    help="must match the unigram table this accompanies")
    ap.add_argument("--prune-min", type=int, default=3,
                    help="drop bigrams seen fewer than N times across strata")
    args = ap.parse_args()

    global _TOKEN_RULE
    _TOKEN_RULE = args.token_rule
    print(f"token rule: {_TOKEN_RULE}")

    if not _CACHE.exists():
        print(f"No source cache at {_CACHE}.\n"
              f"Run: python datasets/places_dataops/build_place_frequencies.py",
              file=sys.stderr)
        return 1

    strata: list[tuple[str, Counter[str]]] = []

    for z in sorted(_CACHE.glob("*.zip")):
        c = _geonames(z)
        if c:
            strata.append((f"geonames-{z.stem}", c))
    for j in sorted(_CACHE.glob("wd_*.json")):
        c: Counter[str] = Counter()
        for label in json.loads(j.read_text(encoding="utf-8")):
            c.update(bigrams(label))
        if c:
            strata.append((j.stem, c))
    wri = _CACHE / "global_power_plant_database.csv"
    if wri.exists():
        c = _csv(wri, ("name",))
        if c:
            strata.append(("wri-power-plants", c))
    for key, rel, fields in _LOCAL:
        p = _REPO / rel
        if p.exists():
            c = _csv(p, fields)
            if c:
                strata.append((key, c))

    if not strata:
        print("No strata found.", file=sys.stderr)
        return 1

    # Equal-mass merge, identical to the token builder: without it the largest
    # stratum sets the vocabulary and a smaller one's common phrases read as rare.
    masses = [sum(c.values()) for _, c in strata]
    target = sum(masses) / len(masses)
    merged: Counter[str] = Counter()
    for (_, c), mass in zip(strata, masses):
        scale = target / mass if mass else 0.0
        for g, n in c.items():
            merged[g] += n * scale

    # Prune on RAW occurrence, so a rare phrase from a small stratum is not
    # preferentially dropped.
    raw: Counter[str] = Counter()
    for _, c in strata:
        raw.update(c)
    before = len(merged)
    merged = Counter({g: n for g, n in merged.items() if raw[g] >= args.prune_min})

    table = TokenFrequencyTable(counts=merged, token_rule=args.token_rule)
    payload = table.to_dict()
    # Content version, same discipline as the unigram table: the phrase table
    # is a scoring input, so a rebuild must be visible in every decision id it
    # touches rather than changing results silently.
    payload["version"] = "sha256:" + hashlib.sha256(
        json.dumps({k: round(v, 4) for k, v in sorted(merged.items())},
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"{len(strata)} strata -> {before:,} bigrams, "
          f"{len(merged):,} after prune-min={args.prune_min}")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")

    print("\nGeneric type phrases must be COMMON:")
    for g in ("general hospital", "primary health", "health post", "medical centre"):
        print(f"  {g:20} distinctiveness={table.distinctiveness(g):.3f}")
    print("\nDistinctive name phrases must be RARE:")
    for g in ("london bridge", "kings college", "king george", "royal london"):
        print(f"  {g:20} distinctiveness={table.distinctiveness(g):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
