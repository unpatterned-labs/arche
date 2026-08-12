# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Three ways to handle the English possessive, measured rather than argued.

`St George's Hospital` tokenises today as ``['st','george','s','hospital']``.
The bare ``s`` is the 4,132-per-million junk token, and ``Queen's`` therefore
shares nothing distinctive with ``Queens``. Three candidate rules:

    KEEP   (today)   George's -> george, s
    STRIP            George's -> george           (drop the possessive marker)
    BOTH             George's -> george, s, georges   (emit alongside, never instead)

Each rule is applied to the **table build and the query together**. Applying it
only at query time redirects a lookup to a token whose count was accumulated
under a different rule, which undercounts by exactly the possessive mass and
biases in the recall-flattering direction. That is why this script rebuilds.

Run from the repo root. Requires the source cache populated by
`datasets/places_dataops/build_place_frequencies.py`.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))

import arche.resolve._tokenfreq as TFMOD  # noqa: E402
from arche.resolve._matcher import _normalise_text  # noqa: E402

_CACHE = _REPO / "datasets" / "data" / "_cache" / "places"
_WORD = re.compile(r"[a-z0-9]+")
# The possessive as it survives `_normalise_text` (which does not strip
# apostrophes): a word character, an apostrophe variant, then a trailing s.
_POSS = re.compile(r"([a-z0-9]+)['’]s\b")

_GN_NAME, _GN_ASCII, _GN_FCLASS, _GN_FCODE = 1, 2, 6, 7
_CODES = ({"HSP", "HSPC", "HSPD", "HSPL"} | {"PS", "PSH", "PSTN"}
          | {"SCH", "SCHA", "SCHC", "SCHL", "SCHM", "SCHN", "SCHT", "UNIV"}
          | {"BLDG", "MKT", "MFG", "MFGB", "MFGPH", "AIRP", "RSTN", "BANK",
             "COURT", "GOVL", "HTL", "LIBR", "MUS", "PO", "POL", "PRN", "REST",
             "STDM", "STNB", "TRIG", "WTRW", "CMTY", "CH", "MSQE", "TMPL"})

_LOCAL = [
    ("data/GRID3_NGA_health_facilities_v2.csv", ("facility_name",)),
    ("data/hfr_kano.csv", ("name", "alternate_name")),
    ("data/hfr_edo.csv", ("name", "alternate_name")),
    ("data/hfr_ondo.csv", ("name", "alternate_name")),
]


def make_tokeniser(rule: str):
    """Return a `_tokens`-compatible function implementing `rule`."""
    def tokens(text: str) -> list[str]:
        norm = _normalise_text(text or "")
        if rule == "keep":
            return _WORD.findall(norm)
        if rule == "strip":
            # Drop the possessive marker: "george's" -> "george".
            return _WORD.findall(_POSS.sub(r"\1", norm))
        if rule == "both":
            # Emit the joined form ALONGSIDE, never instead. Set-union, so the
            # shared-token set is a superset of today's and the gate can only
            # ever see more evidence, not less.
            out = _WORD.findall(norm)
            out.extend(m.group(1) + "s" for m in _POSS.finditer(norm))
            return out
        raise ValueError(rule)
    return tokens


def build_counts(tokens) -> Counter[str]:
    """Rebuild the place unigram counts from the cache under `tokens`."""
    strata: list[Counter[str]] = []
    for z in sorted(_CACHE.glob("*.zip")):
        cc, c = z.stem, Counter()
        with zipfile.ZipFile(z) as zf, zf.open(f"{cc}.txt") as fh:
            for raw in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                col = raw.rstrip("\n").split("\t")
                if len(col) <= _GN_FCODE:
                    continue
                if col[_GN_FCLASS] == "P" or (
                    col[_GN_FCLASS] == "S" and col[_GN_FCODE] in _CODES
                ):
                    c.update(tokens(col[_GN_NAME]))
                    if col[_GN_ASCII] and col[_GN_ASCII] != col[_GN_NAME]:
                        c.update(tokens(col[_GN_ASCII]))
        if c:
            strata.append(c)
    for j in sorted(_CACHE.glob("wd_*.json")):
        c = Counter()
        for label in json.loads(j.read_text(encoding="utf-8")):
            c.update(tokens(label))
        if c:
            strata.append(c)
    wri = _CACHE / "global_power_plant_database.csv"
    if wri.exists():
        c = Counter()
        with open(wri, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for rec in csv.DictReader(fh):
                c.update(tokens(rec.get("name") or ""))
        if c:
            strata.append(c)
    for rel, fields in _LOCAL:
        p = _REPO / rel
        if not p.exists():
            continue
        c = Counter()
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for rec in csv.DictReader(fh):
                for f in fields:
                    c.update(tokens(rec.get(f) or ""))
        if c:
            strata.append(c)

    # Equal-mass merge and raw-occurrence prune, identical to the shipped builder.
    masses = [sum(c.values()) for c in strata]
    target = sum(masses) / len(masses)
    merged: Counter[str] = Counter()
    for c, mass in zip(strata, masses):
        scale = target / mass if mass else 0.0
        for t, n in c.items():
            merged[t] += n * scale
    raw: Counter[str] = Counter()
    for c in strata:
        raw.update(c)
    return Counter({t: n for t, n in merged.items() if raw[t] >= 3})


def measure(label: str, rule: str) -> dict:
    """Patch the tokeniser, rebuild the table, score London and Kano."""
    tokens = make_tokeniser(rule)
    original = TFMOD._tokens
    TFMOD._tokens = tokens
    # `_gate` binds its own tokeniser; keep the two consistent.
    import arche.resolve._gate as GATE
    gate_original = getattr(GATE, "_TOKEN_RE", None)

    try:
        counts = build_counts(tokens)
        table = TFMOD.TokenFrequencyTable(counts=counts, population_scale=True)

        from arche.resolve import crosswalk

        # ---- London ----
        uk = _REPO / "data" / "uk"
        osm = list(csv.DictReader(open(uk / "osm_london_hospitals.csv", encoding="utf-8")))
        wd = list(csv.DictReader(open(uk / "wikidata_london_hospitals.csv", encoding="utf-8")))
        truth = {(r["osm_id"], r["wd_id"])
                 for r in csv.DictReader(open(uk / "truth_pairs_london.csv", encoding="utf-8"))}
        A = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in osm]
        B = [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in wd]
        res = crosswalk(A, B, entity="place", tf=table)
        pred = {(osm[e["a_id"]]["osm_id"], wd[e["b_id"]]["wd_id"]): e for e in res["matches"]}
        m = {k for k, e in pred.items() if k in truth and e["decision"] == "match"}
        r = {k for k, e in pred.items() if k in truth and e["decision"] == "review"}

        # ---- Kano ----
        with open(_REPO / "data" / "GRID3_NGA_health_facilities_v2.csv",
                  encoding="utf-8-sig") as fh:
            grid3 = [x for x in csv.DictReader(fh) if x["state"] == "Kano"]
        with open(_REPO / "data" / "osm_kano.csv", encoding="utf-8-sig") as fh:
            okano = [x for x in csv.DictReader(fh) if x["name"].strip()]
        KA = [{"name": x["name"], "lat": x["lat"], "lon": x["lon"]} for x in okano]
        KB = [{"name": x["facility_name"], "lat": x["latitude"], "lon": x["longitude"]}
              for x in grid3]
        la = {i: (x.get("lga") or "").strip().lower() for i, x in enumerate(okano)}
        lb = {i: (x.get("lga") or "").strip().lower() for i, x in enumerate(grid3)}
        kres = crosswalk(KA, KB, entity="place", tf=table)
        km = sum(1 for e in kres["matches"] if e["decision"] == "match")
        same = diff = 0
        for e in kres["matches"]:
            if e["decision"] != "match":
                continue
            x, y = la.get(e["a_id"], ""), lb.get(e["b_id"], "")
            if x and y:
                same += (x == y)
                diff += (x != y)
        lga = 100 * same / (same + diff) if (same + diff) else 0.0

        print(f"  {label:6} vocab={len(counts):>7,}  london match={len(m):>3}/{len(truth)} "
              f"review={len(r):>3}   kano match={km:>4} LGA={lga:.1f}%")
        return {"matched": m, "review": r, "kano_match": km, "kano_lga": lga,
                "table": table}
    finally:
        TFMOD._tokens = original
        if gate_original is not None:
            GATE._TOKEN_RE = gate_original


def main() -> int:
    if not _CACHE.exists():
        print(f"No cache at {_CACHE}; run build_place_frequencies.py first",
              file=sys.stderr)
        return 1
    print("Possessive rules, table rebuilt under each rule\n")
    out = {rule: measure(rule, rule) for rule in ("keep", "strip", "both")}

    base = out["keep"]["matched"]
    print("\nmovement against KEEP (today):")
    for rule in ("strip", "both"):
        m = out[rule]["matched"]
        print(f"  {rule:6} recovered={len(m - base):>2}  lost={len(base - m):>2}"
              f"  kano_delta={out[rule]['kano_match'] - out['keep']['kano_match']:+d}")

    print("\ntokens that decide the London cases:")
    for t in ("georges", "marys", "queens", "kings", "george", "mary", "queen", "s"):
        row = "  " + f"{t:9}"
        for rule in ("keep", "strip", "both"):
            row += f"  {rule}={out[rule]['table'].distinctiveness(t):.3f}"
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
