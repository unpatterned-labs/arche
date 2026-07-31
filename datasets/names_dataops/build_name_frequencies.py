# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build the population-scale name-frequency table shipped with arche.

The moat: agreement on a *common* name ("Ibrahim", "Smith", "Mohammed") is weak
evidence two records are the same person; agreement on a *rare* one is strong.
`arche.resolve.TokenFrequencyTable` turns a token's population frequency into a
distinctiveness weight — but only if it has real population data. This script
builds that data from two public sources and writes the compact table that
`TokenFrequencyTable.default()` loads.

Sources
-------
1. **US Census 2010 surnames** — 162,253 surnames with real occurrence counts.
   Public domain (US Census Bureau). The Western-anchor + real-frequency ground
   truth. Auto-downloaded on first run.
   https://www.census.gov/data/developers/data-sets/surnames.2010.html

2. **African names lexicon** (`datasets/data/african_names_lexicon_v1.csv`) —
   13,342 African given/family names with Wikidata occurrence counts, built by
   `datasets/names_dataops` from Wikidata (the ParaNames upstream). CC BY 4.0.
   This is the African distinctiveness signal Western surname lists lack.

Scale reconciliation
--------------------
Census counts run to millions; the Wikidata-derived African counts top out near
~1e3. Summing raw counts would let Census drown the African signal, so each
source is normalised to a common total before merging (a mixture of two
distributions), with an optional boost for the African source since it is the
moat. The merged table is pruned to its common head (rare tokens all fall back
to the unknown-frequency floor = maximally distinctive, which is already
correct) to keep the shipped asset small.

Usage
-----
    python datasets/names_dataops/build_name_frequencies.py
    python datasets/names_dataops/build_name_frequencies.py --african-weight 2.0 --prune-min 3
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

# Import the shipped table type so the builder and the runtime agree exactly.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
from arche.resolve._tokenfreq import TokenFrequencyTable  # noqa: E402

_CENSUS_URL = "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
_CENSUS_CSV = "Names_2010Census.csv"
_AFRICAN_LEXICON = _REPO / "datasets" / "data" / "african_names_lexicon_v1.csv"
_DEFAULT_OUT = (
    _REPO / "packages" / "arche-core" / "src" / "arche" / "resolve" / "_data"
    / "name_frequencies.json.gz"
)
# Normalise each source to this nominal total before mixing, so counts stay
# integer-scale and neither source's magnitude dominates the other.
_NOMINAL = 1_000_000


def load_census_counts(cache_dir: Path) -> dict[str, int]:
    """{surname: count} from the 2010 Census surname file (auto-downloaded)."""
    csv_path = cache_dir / _CENSUS_CSV
    if not csv_path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = cache_dir / "names.zip"
        print(f"  downloading Census surnames -> {zip_path}")
        urllib.request.urlretrieve(_CENSUS_URL, zip_path)  # noqa: S310 (public gov URL)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract(_CENSUS_CSV, cache_dir)
    counts: dict[str, int] = {}
    with csv_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["name"].strip()
            if name.upper() == "ALL OTHER NAMES":
                continue
            try:
                counts[name] = int(row["count"])
            except (KeyError, ValueError):
                continue
    return counts


def load_african_counts(lexicon_csv: Path) -> dict[str, int]:
    """{name: occurrence_count} from the African names lexicon."""
    counts: Counter[str] = Counter()
    with lexicon_csv.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("name_display") or row.get("name") or "").strip()
            if not name:
                continue
            try:
                c = int(row.get("occurrence_count") or row.get("total_evidence_count") or 1)
            except ValueError:
                c = 1
            counts[name] += max(c, 1)
    return dict(counts)


def build(
    *,
    cache_dir: Path,
    lexicon_csv: Path = _AFRICAN_LEXICON,
    out_path: Path = _DEFAULT_OUT,
    african_weight: float = 1.0,
    prune_min: float = 2.0,
) -> TokenFrequencyTable:
    """Build, merge, prune, and save the default name-frequency table."""
    print("Loading US Census 2010 surnames (public domain)...")
    census = TokenFrequencyTable.from_counts(load_census_counts(cache_dir))
    print(f"  census: {census.vocabulary_size:,} tokens, {census.total_count:,.0f} occ")

    print("Loading African names lexicon (Wikidata, CC BY 4.0)...")
    african = TokenFrequencyTable.from_counts(load_african_counts(lexicon_csv))
    print(f"  african: {african.vocabulary_size:,} tokens, {african.total_count:,.0f} occ")

    # Normalise each source to a common nominal total, then mix (African boosted).
    merged = census.merge(
        african,
        weight=_NOMINAL / max(census.total_count, 1),
        other_weight=african_weight * _NOMINAL / max(african.total_count, 1),
    )
    print(f"  merged (pre-prune): {merged.vocabulary_size:,} tokens")

    # Prune the rare tail: pruned tokens fall back to the unknown-frequency floor,
    # which is already "maximally distinctive" — the correct treatment for a rare
    # name. Keeping only the common head is what makes the asset small.
    pruned = {t: c for t, c in merged._as_counts().items() if c >= prune_min}
    table = TokenFrequencyTable(counts=pruned)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.save(out_path)
    size_kb = out_path.stat().st_size / 1024
    print(f"Saved {table.vocabulary_size:,} tokens -> {out_path} ({size_kb:.0f} KB)")
    return table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--lexicon", type=Path, default=_AFRICAN_LEXICON)
    ap.add_argument(
        "--cache-dir", type=Path, default=_REPO / "datasets" / "data" / "_cache"
    )
    ap.add_argument(
        "--african-weight", type=float, default=1.0,
        help="Boost the African source relative to Census (moat). Default 1.0 (equal mix).",
    )
    ap.add_argument(
        "--prune-min", type=float, default=2.0,
        help="Drop tokens with a merged (normalised) count below this. Default 2.0.",
    )
    args = ap.parse_args(argv)
    table = build(
        cache_dir=args.cache_dir,
        lexicon_csv=args.lexicon,
        out_path=args.out,
        african_weight=args.african_weight,
        prune_min=args.prune_min,
    )
    # Sanity: a common name must be less distinctive than a rare one.
    common, rare = "ibrahim", "gyaranya"
    print(
        f"Sanity: distinctiveness({common})={table.distinctiveness(common):.2f} "
        f"< distinctiveness({rare})={table.distinctiveness(rare):.2f} "
        f"-> {table.distinctiveness(common) < table.distinctiveness(rare)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
