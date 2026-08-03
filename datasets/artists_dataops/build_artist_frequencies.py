# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build the population-scale ARTIST name-frequency table shipped with arche.

Same moat, different entity type: agreement on a *common* catalog token ("DJ",
"Boy", "Black", "Young", "Band") is weak evidence two credit lines are the same
artist; agreement on a rare one ("Ogulu", "Openiyi") is strong.
`TokenFrequencyTable.default(domain="artist")` loads the table this script
writes — the artist counterpart of the person table built by
`datasets/names_dataops/build_name_frequencies.py`.

Source
------
**MusicBrainz artist JSON dump** (CC0). ~2.5M artists with names + aliases.
The full `artist.tar.xz` is ~1.7 GB, so this script *streams* the archive and
stops after `--limit` artists (default 500k). The dump is ordered by MBID
(effectively random), so an early-stop prefix is an unbiased sample for token
frequencies.
https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/

Usage
-----
    python datasets/artists_dataops/build_artist_frequencies.py
    python datasets/artists_dataops/build_artist_frequencies.py --limit 500000 --prune-min 3
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import urllib.request
from collections import Counter
from pathlib import Path

# Import the shipped table type so the builder and the runtime agree exactly.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "arche-core" / "src"))
from arche.resolve._tokenfreq import TokenFrequencyTable, _tokens  # noqa: E402

_BASE = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps"
_UA = "arche-dataops/0.2 (https://unpatterned.org; connect@unpatterned.org)"
_DEFAULT_OUT = (
    _REPO / "packages" / "arche-core" / "src" / "arche" / "resolve" / "_data"
    / "artist_frequencies.json.gz"
)
_DEFAULT_CACHE = _REPO / "datasets" / "data" / "_cache" / "artist_token_counts.json"


def latest_dump() -> str:
    req = urllib.request.Request(f"{_BASE}/LATEST", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return resp.read().decode().strip()


def stream_counts(
    dump: str, limit: int, *, include_aliases: bool = True
) -> tuple[Counter[str], int, int]:
    """Token counts over the first ``limit`` artists of the streamed dump.

    Counts each artist's primary name once and each alias name-form once —
    alias forms are part of the name population catalogs actually contain.
    Returns ``(counts, artists_seen, name_forms_seen)``.
    """
    url = f"{_BASE}/{dump}/artist.tar.xz"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    resp = urllib.request.urlopen(req, timeout=120)  # noqa: S310
    counts: Counter[str] = Counter()
    artists = forms = 0
    try:
        with tarfile.open(fileobj=resp, mode="r|xz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith("artist"):
                    continue
                fh = tar.extractfile(member)
                assert fh is not None
                for line in fh:
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    names = [d.get("name") or ""]
                    if include_aliases:
                        names += [a.get("name") or "" for a in d.get("aliases") or []]
                    for n in names:
                        toks = _tokens(n)
                        if toks:
                            counts.update(toks)
                            forms += 1
                    artists += 1
                    if artists % 50_000 == 0:
                        print(f"  ...{artists:,} artists, {len(counts):,} tokens",
                              flush=True)
                    if artists >= limit:
                        return counts, artists, forms
                break  # only the artist member matters
    finally:
        resp.close()
    return counts, artists, forms


def build(
    *,
    dump: str | None,
    limit: int,
    out_path: Path,
    counts_cache: Path,
    prune_min: float,
) -> TokenFrequencyTable:
    if counts_cache.exists():
        print(f"Loading cached token counts from {counts_cache}")
        cached = json.loads(counts_cache.read_text(encoding="utf-8"))
        counts = Counter({k: int(v) for k, v in cached["counts"].items()})
        artists, forms = cached["artists"], cached["name_forms"]
        dump = cached.get("dump", dump)
    else:
        dump = dump or latest_dump()
        print(f"Streaming MusicBrainz artist dump {dump} (stop at {limit:,} artists)...")
        counts, artists, forms = stream_counts(dump, limit)
        counts_cache.parent.mkdir(parents=True, exist_ok=True)
        counts_cache.write_text(
            json.dumps({"dump": dump, "artists": artists, "name_forms": forms,
                        "counts": dict(counts)}),
            encoding="utf-8",
        )
    print(f"  sample: {artists:,} artists, {forms:,} name forms, "
          f"{len(counts):,} distinct tokens (dump {dump})")

    # Prune the rare tail: pruned tokens fall back to the unknown-frequency
    # floor (= maximally distinctive), which is the correct treatment for a
    # rare artist token — pruning only shrinks the shipped asset.
    pruned = {t: float(c) for t, c in counts.items() if c >= prune_min}
    table = TokenFrequencyTable(counts=pruned)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.save(out_path)
    size_kb = out_path.stat().st_size / 1024
    print(f"Saved {table.vocabulary_size:,} tokens -> {out_path} ({size_kb:.0f} KB)")
    return table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", default=None,
                    help="Dump directory name (default: fetch LATEST).")
    ap.add_argument("--limit", type=int, default=500_000,
                    help="Artists to sample from the stream. Default 500k of ~2.5M.")
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--counts-cache", type=Path, default=_DEFAULT_CACHE,
                    help="Raw token-count cache; delete to re-stream.")
    ap.add_argument("--prune-min", type=float, default=2.0,
                    help="Drop tokens seen fewer than this many times. Default 2.")
    args = ap.parse_args(argv)
    table = build(dump=args.dump, limit=args.limit, out_path=args.out,
                  counts_cache=args.counts_cache, prune_min=args.prune_min)
    # Sanity: a ubiquitous catalog token must be less distinctive than a rare one.
    common, rare = "dj", "ogulu"
    print(
        f"Sanity: distinctiveness({common})={table.distinctiveness(common):.2f} "
        f"< distinctiveness({rare})={table.distinctiveness(rare):.2f} "
        f"-> {table.distinctiveness(common) < table.distinctiveness(rare)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
