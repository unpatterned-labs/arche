# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Pull MusicBrainz alias sets for the artists in the Wikidata alias pull.

    uv run python datasets/artists_dataops/pull_musicbrainz.py

Why a second source
-------------------
The variant-list ablation (plan §7d) gives Splink a list of name variants and
asks what it is worth. If the list and the truth labels come from the same
source, "with list" wins by construction and the number means nothing. So the
**truth** is Wikidata's alias groups (`datasets/data/wikidata_artist_aliases.jsonl`)
and the **list** is MusicBrainz's -- two editorial communities, two sets of
opinions about what an artist is called. Where they disagree is where the
experiment lives.

How the two are joined
----------------------
Not by name. A name-only MusicBrainz search for `Tyla` returns a UK artist of
the same name (the wrong-Tyla lesson, recorded in
`datasets/artist_equivalences/afrobeats.yaml`). Wikidata carries the
MusicBrainz artist id as property **P434**, so the join is by identifier: QID
-> MBID via WDQS, then MBID -> alias set via the MusicBrainz web service.
Artists without a P434 are reported and skipped, never guessed.

Rate and courtesy
-----------------
MusicBrainz asks for at most one request per second and a User-Agent that
says who is calling. Both are honoured. Every response is cached under
`datasets/data/_cache/musicbrainz/<mbid>.json`, so a rerun costs nothing and
an interrupted run resumes where it stopped.

Licence
-------
MusicBrainz core data (artist names, aliases, relationships) is CC0. Wikidata
is CC0. Nothing here needs permission to publish.
"""
from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
WIKIDATA_ALIASES = _REPO / "datasets" / "data" / "wikidata_artist_aliases.jsonl"
OUT = _REPO / "datasets" / "data" / "musicbrainz_artist_aliases.jsonl"
CACHE = _REPO / "datasets" / "data" / "_cache" / "musicbrainz"

WDQS = "https://query.wikidata.org/sparql"
MB = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = "arche-datasets/0.1 (https://github.com/unpatterned-labs/arche)"

#: MusicBrainz's published limit is one request per second. A little over,
#: because the clock that matters is theirs.
MB_PAUSE = 1.1

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

_MBID_QUERY = """
SELECT ?artist ?mbid WHERE {{
  VALUES ?artist {{ {qids} }}
  ?artist wdt:P434 ?mbid .
}}
"""


def _get(url: str, *, accept: str, timeout: int = 60, attempts: int = 8,
         throttle_wait: float = 5.0) -> Any:
    """One GET with retries.

    ``throttle_wait`` is the pause after a 503. MusicBrainz answers a request
    that lands a shade inside its one-per-second window with a 503 and
    nothing else is wrong; the first version of this script backed off
    5/10/20 s on each one and averaged fourteen seconds per artist. Two
    seconds is enough there. WDQS keeps the longer, doubling wait.
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": accept})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as fh:
                return json.load(fh)
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                # 404: MusicBrainz has no such artist (a merged or deleted
                # MBID that Wikidata still carries). 400: the value Wikidata
                # holds as a P434 is not an MBID at all. Both are reported
                # by the caller and skipped, never guessed around.
                print(f"    {exc.code} for {url}", file=sys.stderr)
                return None
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                wait = throttle_wait if exc.code == 503 else 5 * (2 ** attempt)
                time.sleep(wait)
                continue
            raise
        except (TimeoutError, urllib.error.URLError, ConnectionError,
                http.client.HTTPException) as exc:
            if attempt < attempts - 1:
                print(f"    {type(exc).__name__}; retrying", file=sys.stderr)
                time.sleep(5 * (2 ** attempt))
                continue
            raise
    return None


def mbids_for(qids: list[str], *, chunk: int = 150) -> dict[str, str]:
    """QID -> MBID via P434. Chunked VALUES keeps each query cheap."""
    found: dict[str, str] = {}
    for i in range(0, len(qids), chunk):
        block = " ".join(f"wd:{q}" for q in qids[i:i + chunk])
        query = _MBID_QUERY.format(qids=block)
        url = WDQS + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
        rows = _get(url, accept="application/sparql-results+json")
        for row in (rows or {}).get("results", {}).get("bindings", []):
            qid = row["artist"]["value"].rsplit("/", 1)[-1]
            # P434 is meant to hold a bare MBID. In this pull it also holds
            # full MusicBrainz URLs, and strings like `Hondread` and `Gia Rồi`
            # that are not identifiers at all. Take the UUID if there is one
            # and report the rest; a value that is not an MBID is not made
            # into one.
            m = _UUID.search(row["mbid"]["value"])
            if m:
                found[qid] = m.group(0).lower()
            else:
                print(f"    {qid}: P434 is not an MBID: {row['mbid']['value']!r}",
                      file=sys.stderr)
        print(f"  P434: {min(i + chunk, len(qids))}/{len(qids)} asked, "
              f"{len(found)} found", flush=True)
        time.sleep(1.0)
    return found


def artist(mbid: str) -> dict[str, Any] | None:
    """One MusicBrainz artist with aliases, from cache or the service."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{mbid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    url = MB + mbid + "?" + urllib.parse.urlencode({"inc": "aliases", "fmt": "json"})
    data = _get(url, accept="application/json", throttle_wait=2.0)
    time.sleep(MB_PAUSE)
    if data is None:
        return None
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many artists (0 = all)")
    args = ap.parse_args()

    groups = [json.loads(line) for line in
              WIKIDATA_ALIASES.read_text(encoding="utf-8").splitlines() if line]
    qids = [g["entity_id"] for g in groups]
    if args.limit:
        qids = qids[:args.limit]
    print(f"  {len(qids)} Wikidata artists", flush=True)

    mbids = mbids_for(qids)
    missing = [q for q in qids if q not in mbids]
    print(f"  {len(mbids)} carry a MusicBrainz id (P434); "
          f"{len(missing)} do not and are skipped\n", flush=True)

    by_qid = {g["entity_id"]: g for g in groups}
    written = 0
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for n, (qid, mbid) in enumerate(mbids.items(), 1):
            data = artist(mbid)
            if data is None:
                print(f"    {mbid}: not found", file=sys.stderr)
                continue
            aliases = [{"name": a.get("name"), "sort_name": a.get("sort-name"),
                        "type": a.get("type"), "locale": a.get("locale"),
                        "primary": bool(a.get("primary"))}
                       for a in data.get("aliases", []) if a.get("name")]
            row = {
                "entity_id": qid,
                "mbid": mbid,
                "wikidata_canonical": by_qid[qid]["canonical"],
                "mb_name": data.get("name"),
                "mb_sort_name": data.get("sort-name"),
                "mb_disambiguation": data.get("disambiguation") or None,
                "mb_country": data.get("country"),
                "mb_type": data.get("type"),
                "aliases": aliases,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            if n % 50 == 0:
                print(f"  {n}/{len(mbids)} fetched", flush=True)

    print(f"\n  wrote {written} rows to {OUT.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
