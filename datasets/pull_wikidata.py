#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Pull real names from Wikidata (CC0) — the two things the generator cannot invent.

    python datasets/pull_wikidata.py names   --out datasets/data/wikidata_name_pairs.jsonl
    python datasets/pull_wikidata.py aliases --out datasets/data/wikidata_artist_aliases.jsonl

**`names`** — real *given + family* pairs with a country, from people Wikidata
holds. This is what the synthetic generator has no way to make up: it draws the
two halves of a name independently and produces `Zubeyde Saliou`, and the
notebook measured the result as **0.0% regional signal against 90.4% in real
data**. A conditional table built from real pairs is the fix (plan N1), and a
table derived from public data is `public-data-derived` provenance rather than
`synthetic-assumption`.

**`aliases`** — artists with their alternate names: stage name, legal name,
orthographic variants. `Jua Cali` and `Paul Julius Nunda` are one person;
`Achieng Abura`, `Achien'g Abura` and `Lydia Achieng Abura` are one person
written four ways. Ground truth comes free, because the entity is a QID. This
is the variant list for the ablation (plan N4): does supplying it buy recall,
and what does it cost in false merges?

Licence. Wikidata is **CC0** — no permission needed, which is the entire reason
this lane exists while `ai4privacy`, `i2b2` and OpenSanctions remain blocked.
Attribution is still good manners and the data card carries it.

Etiquette. WDQS is a shared public service. This pager keeps one request in
flight, sleeps between pages, sends a real User-Agent with contact details as
the service asks, and backs off on 429 and 5xx. Do not remove those.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = ("arche-synthetic/0.0.1 (https://unpatterned.org; "
              "connect@unpatterned.org) python-urllib")

#: Countries to pull. Wikidata QIDs. Widen deliberately: every addition is more
#: load on a free service and more rows to curate.
COUNTRIES = {
    "NG": "wd:Q1033", "KE": "wd:Q114", "ZA": "wd:Q258", "GH": "wd:Q117",
    "TZ": "wd:Q924", "UG": "wd:Q1036", "SN": "wd:Q1041", "CI": "wd:Q1008",
    "ET": "wd:Q115", "CM": "wd:Q1009", "ZW": "wd:Q954", "ZM": "wd:Q953",
}

#: Occupations that count as "artist" for the alias pull.
MUSICIANS = "wd:Q177220 wd:Q639 wd:Q36834 wd:Q488205 wd:Q753110"

# One country at a time, no ORDER BY and no OPTIONAL. Both were what made this
# too expensive: WDQS answered the sorted, optional-carrying version by closing
# the connection, at every page size tried. Per country, plain, it returns
# 5,000 rows in about three seconds.
_NAMES = """
SELECT ?givenLabel ?familyLabel WHERE {{
  ?person wdt:P31 wd:Q5 ;
          wdt:P735 ?given ;
          wdt:P734 ?family ;
          wdt:P27 {country} .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT {limit}
"""

_ALIASES = """
SELECT ?artist ?artistLabel ?alias ?countryLabel WHERE {{
  ?artist wdt:P31 wd:Q5 ;
          wdt:P106 ?occ ;
          wdt:P27 ?country ;
          skos:altLabel ?alias .
  VALUES ?occ {{ {occupations} }}
  VALUES ?country {{ {countries} }}
  FILTER(LANG(?alias) = "en")
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
ORDER BY ?artist
LIMIT {limit} OFFSET {offset}
"""


def _ask(query: str, *, timeout: int = 180, attempts: int = 4) -> list[dict[str, Any]]:
    """One SPARQL request, with the back-off a shared public service deserves."""
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    })
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as fh:
                return json.load(fh)["results"]["bindings"]
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                wait = 5 * (2 ** attempt)
                print(f"    {exc.code}; waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except (TimeoutError, urllib.error.URLError, ConnectionError,
                http.client.HTTPException) as exc:
            # WDQS answers a query it considers too expensive by closing the
            # connection rather than returning an error, which arrives as
            # http.client.RemoteDisconnected -- a ConnectionError, not a
            # URLError, so it escaped an earlier version of this handler and
            # ended the run instead of being retried.
            if attempt < attempts - 1:
                print(f"    {type(exc).__name__}; retrying", file=sys.stderr)
                time.sleep(5 * (2 ** attempt))
                continue
            raise
    return []


def _pages(template: str, *, limit: int, cap: int, pause: float,
           **fields: str) -> Iterator[dict[str, Any]]:
    """Page through a query until it runs dry or the cap is reached.

    Used by the alias pull only. The name pull queries one country at a time
    instead, because paging it with ORDER BY is what WDQS refuses.
    """
    offset = 0
    while offset < cap:
        query = template.format(limit=min(limit, cap - offset), offset=offset, **fields)
        rows = _ask(query)
        if not rows:
            return
        for row in rows:
            yield {k: v["value"] for k, v in row.items()}
        got = len(rows)
        print(f"    +{got:,} (offset {offset:,})", file=sys.stderr)
        offset += got
        if got < limit:
            return
        time.sleep(pause)


def pull_names(cap: int, limit: int, pause: float) -> list[dict[str, Any]]:
    """Real given+family pairs, a country at a time.

    The pair is the point. A list of given names and a list of family names is
    what the generator already has; what it cannot invent is which ones go
    *together*, and that is exactly what P735 and P734 on one person record.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    per_country = max(200, cap // max(len(COUNTRIES), 1))
    for iso, qid in COUNTRIES.items():
        if len(out) >= cap:
            break
        query = _NAMES.format(country=qid, limit=min(limit, per_country))
        try:
            rows = _ask(query)
        except Exception as exc:  # one country failing must not lose the rest
            print(f"    {iso}: {type(exc).__name__}, skipped", file=sys.stderr)
            continue
        kept = 0
        for row in rows:
            given = row.get("givenLabel", {}).get("value", "")
            family = row.get("familyLabel", {}).get("value", "")
            # An unlabelled entity comes back as its bare QID -- `Faith
            # Q16870958`. Either half can be affected, and an earlier version
            # of this filter only checked the given name.
            if not given or not family or _is_qid(given) or _is_qid(family):
                continue
            key = (given, family, iso)
            if key in seen:
                continue
            seen.add(key)
            out.append({"given": given, "family": family, "country": iso})
            kept += 1
        print(f"    {iso}: {kept:,} pairs", file=sys.stderr)
        time.sleep(pause)
    return out


def _is_qid(text: str) -> bool:
    return text.startswith("Q") and text[1:].isdigit()


def pull_aliases(cap: int, limit: int, pause: float) -> list[dict[str, Any]]:
    """Artists grouped by QID, with every English alternate name."""
    countries = " ".join(COUNTRIES.values())
    grouped: dict[str, dict[str, Any]] = {}
    for row in _pages(_ALIASES, limit=limit, cap=cap, pause=pause,
                      countries=countries, occupations=MUSICIANS):
        qid = row["artist"].rsplit("/", 1)[-1]
        entry = grouped.setdefault(qid, {
            "entity_id": qid,
            "canonical": row.get("artistLabel", ""),
            "country": row.get("countryLabel", ""),
            "variants": [],
        })
        alias = row.get("alias", "").strip()
        if alias and alias != entry["canonical"] and alias not in entry["variants"]:
            entry["variants"].append(alias)
    # An entity with no variant teaches the ablation nothing.
    return [e for e in grouped.values() if e["variants"] and e["canonical"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("names", "aliases"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=int, default=40_000, help="stop after this many rows")
    ap.add_argument("--limit", type=int, default=None,
                    help="rows per request (default: 1,000 for names, 5,000 for "
                         "aliases -- the name query carries two OPTIONALs and "
                         "WDQS drops it at larger page sizes)")
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between requests")
    args = ap.parse_args()

    limit = args.limit or (1_000 if args.what == "names" else 5_000)
    print(f"  pulling {args.what} from Wikidata (CC0), cap {args.cap:,}, "
          f"page {limit:,}", file=sys.stderr)
    started = time.perf_counter()
    rows = (pull_names if args.what == "names" else pull_aliases)(
        args.cap, limit, args.pause)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    print(f"  {len(rows):,} rows -> {out}  ({time.perf_counter() - started:.0f}s)",
          file=sys.stderr)
    if args.what == "aliases":
        variants = sum(len(r["variants"]) for r in rows)
        print(f"  {variants:,} variants across {len(rows):,} entities "
              f"({variants / max(len(rows), 1):.1f} each)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
