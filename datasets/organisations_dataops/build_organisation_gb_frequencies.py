#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Build the GB organisation frequency table from the Companies House name list.

    python datasets/organisations_dataops/build_organisation_gb_frequencies.py \\
        --names <snapshot>/names.parquet --release 2026-10-01

Selectable as ``tf="organisation_gb"``. It is **not** the default for the
``organisation`` pack: the shipped default stays the GLEIF table
(``organisation_frequencies.json.gz``) until a change of default is measured
across more than one population.

Why this exists
---------------
The GLEIF table knows global corporate naming and almost nothing about the UK
register's own phrases. In Exp 000 (GIAS academy trusts against Companies
House) the organisation pack returned ``match`` for distinct organisations at
0.70-0.84, e.g. ``THE ROMERO CATHOLIC ACADEMY`` against ``THE PAINSLEY
CATHOLIC ACADEMY`` at 0.703: ``catholic``, ``academy``, ``learning`` and
``trust`` are rare among 52,875 LEI names and ordinary among 6.35M UK company
names. Counting the register itself is the fix; no curated list can keep pace
with a register's vocabulary.

Source and licence
------------------
Companies House, *Free Company Data Product* (BasicCompanyDataAsOneFile), via
https://download.companieshouse.gov.uk/en_output.html.

**Open Government Licence v3.0** (OGL-UK-3.0). OGL is an attribution licence
with no share-alike: a derived aggregate may be redistributed inside an
Apache-2.0 wheel provided the attribution statement travels with it. The
statement is recorded in the table's ``provenance`` block and in
``SOURCES.md``:

    Contains public sector information licensed under the Open Government
    Licence v3.0 (Companies House).

The input is Renyi's normalised snapshot ``names.parquet`` (columns
``company_number, name, kind, changed_on``; ``kind`` is ``current`` or
``previous``). It is a projection of the CH zip, nothing added; its sha256 is
recorded in the provenance so the table names the exact input it was counted
from. The shipped table is an aggregate of token counts: no company name, and
no company number, is in it.

Counting
--------
* Every name row counts once: 5,704,711 current names plus 648,459 previous
  names. Previous names are included because a supplier file carries old names
  as often as new ones, and a token common only in old names is still common.
  A company that renamed contributes its shared tokens twice; that is a small,
  conservative bias (it can only make a token look commoner).
* Tokenised with the library's own ``plain`` rule (the GLEIF table's rule), so
  a lookup lands on a count accumulated the same way.
* The curated layer ``organisation_tokens.yaml`` is applied last, exactly as in
  the GLEIF builder. It only ever raises a count.

Vocabulary cap (why the artefact is small, and why the cap is lossless)
-----------------------------------------------------------------------
The register has well over a million distinct tokens, most of them seen once.
``distinctiveness`` is ``min(1, -log10(rel_freq) / 5)``, so every token rarer
than ``rel_freq = 1e-5`` already scores exactly 1.0. The table therefore keeps
only tokens with ``rel_freq >= 1e-5`` (``--min-rel``), stores the *original*
total so kept tokens keep their true relative frequency, and sets
``unknown_floor = 1e-5`` so a dropped (or never-seen) token reads as rarity
1.0 — the same answer it would have had uncapped. The cap is lossless for
``distinctiveness`` and therefore for every gate and the ``tftoken``
comparator. It is *not* lossless for ``u_for`` / ``rel_freq`` on dropped
tokens (they return the floor), which no shipped pack consults.

Note the floor differs from the GLEIF table's 5e-5. That is deliberate: a
corpus of ~20M tokens can certify rarity far below 5e-5, and the GLEIF floor
would make a dropped token (count < ~220) look *commoner* than a kept one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "packages" / "arche-core" / "src" / "arche" / "resolve" / "_data"
SOURCE_URL = "https://download.companieshouse.gov.uk/en_output.html"
LICENCE = "OGL-UK-3.0"
ATTRIBUTION = ("Contains public sector information licensed under the Open "
               "Government Licence v3.0 (Companies House).")
#: See "Vocabulary cap" above. 1e-5 is where distinctiveness saturates at 1.0.
MIN_REL = 1e-5


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_names(path: Path) -> tuple[list[tuple[str, str]], Counter]:
    """``[(name, kind)]`` from the snapshot parquet, plus a count per kind."""
    import duckdb

    rows = duckdb.connect().execute(
        "SELECT name, kind FROM read_parquet(?) WHERE name IS NOT NULL",
        [str(path)],
    ).fetchall()
    return rows, Counter(k for _, k in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--names", type=Path, required=True,
                    help="Companies House names.parquet (company_number, name, kind, changed_on)")
    ap.add_argument("--release", required=True,
                    help="CH release date of the snapshot, e.g. 2026-10-01")
    ap.add_argument("--min-rel", type=float, default=MIN_REL,
                    help="drop tokens rarer than this relative frequency (default 1e-5)")
    ap.add_argument("--out", type=Path,
                    default=DATA / "organisation_gb_frequencies.json.gz")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))
    from arche.resolve._tokenfreq import DEFAULT_TOKEN_RULE, TokenFrequencyTable, _tokens

    sys.path.insert(0, str(HERE))
    from build_organisation_frequencies import _apply_curated_layer

    t0 = time.perf_counter()
    print(f"reading {args.names}", flush=True)
    input_sha = _sha256(args.names)
    rows, kinds = _read_names(args.names)
    print(f"  {len(rows):,} name rows {dict(kinds)} "
          f"({time.perf_counter() - t0:.0f}s)", flush=True)
    if len(rows) < 1_000_000:
        print("ERROR: fewer than 1M names; this is not the register.", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    for i, (name, _) in enumerate(rows):
        counts.update(_tokens(name, DEFAULT_TOKEN_RULE))
        if i and i % 1_000_000 == 0:
            print(f"  tokenised {i:,} ({time.perf_counter() - t0:.0f}s)", flush=True)
    del rows
    total = float(sum(counts.values()))
    vocab_full = len(counts)
    print(f"  {vocab_full:,} distinct tokens, {total:,.0f} occurrences", flush=True)

    # Curated layer first, on the full vocabulary, so a raised generic token
    # survives the cap and the total it is raised against is the real one.
    table = TokenFrequencyTable(counts=counts, unknown_floor=args.min_rel,
                                population_scale=True, token_rule=DEFAULT_TOKEN_RULE)
    report = _apply_curated_layer(table, DATA / "organisation_tokens.yaml")
    full_counts = table._counts                              # noqa: SLF001
    full_total = float(sum(full_counts.values()))

    keep_at = args.min_rel * full_total
    kept = {t: c for t, c in full_counts.items() if c >= keep_at}
    capped = TokenFrequencyTable(counts=kept, total=full_total,
                                 unknown_floor=args.min_rel, population_scale=True,
                                 token_rule=DEFAULT_TOKEN_RULE)
    payload = capped.to_dict()
    # Content version over the counts, carried into `pins` and so into every
    # `decision_id` scored against this table (same discipline as `place`).
    payload["version"] = "sha256:" + hashlib.sha256(
        json.dumps({"total": round(full_total, 4), "floor": args.min_rel,
                    "counts": {k: round(v, 4) for k, v in sorted(kept.items())}},
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    payload["curated"] = report
    payload["provenance"] = {
        "built_by": "datasets/organisations_dataops/build_organisation_gb_frequencies.py",
        "domain": "organisation_gb",
        "sources": [{
            "stratum": f"companies-house-{args.release}",
            "publisher": "Companies House",
            "product": "Free Company Data Product (BasicCompanyDataAsOneFile)",
            "release": args.release,
            "url": SOURCE_URL,
            "licence": LICENCE,
            "attribution": ATTRIBUTION,
            "input": args.names.name,
            "input_sha256": input_sha,
            "records": dict(sorted(kinds.items())),
        }],
        "counting": "one count per name row (current + previous names); "
                    "tokens under the 'plain' rule; curated layer applied last",
        "vocabulary_cap": {
            "min_rel_freq": args.min_rel,
            "min_count": round(keep_at, 2),
            "vocabulary_full": vocab_full,
            "vocabulary_kept": len(kept),
            "lossless_for": "distinctiveness (saturates at 1.0 below 1e-5; "
                            "unknown_floor set to the cap)",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    with gzip.open(args.out, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    print(f"kept {len(kept):,} of {vocab_full:,} tokens (count >= {keep_at:.0f})")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB) "
          f"version {payload['version']} in {time.perf_counter() - t0:.0f}s")
    print(f"curated layer: {len(report['generic'])} raised, "
          f"{len(report['skipped'])} already common")
    print("sanity — register-common tokens must be COMMON:")
    for t in ("limited", "ltd", "academy", "trust", "catholic", "learning",
              "multi", "schools", "education", "holdings", "services"):
        print(f"  {t:12} distinctiveness={capped.distinctiveness(t):.4f}")
    print("sanity — distinctive tokens must stay RARE:")
    for t in ("romero", "painsley", "tove", "weaver", "kuapa"):
        print(f"  {t:12} distinctiveness={capped.distinctiveness(t):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
