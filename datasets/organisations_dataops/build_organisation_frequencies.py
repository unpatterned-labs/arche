#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Build the organisation population frequency table from GLEIF LEI records.

    python datasets/organisations_dataops/build_organisation_frequencies.py

Why this exists
---------------
`ENTITY_PACKS["organisation"]` shipped without a population table, and the
distinctive-signal cap that stops an identical-but-generic name clearing the
match gate is conditioned on ``tf.population_scale``. A table self-calibrated
over the two lists being linked is correctly *not* one — fourteen records
cannot know that ``Central`` is common — so without this asset two records both
named ``Central Cooperative Society`` merge on a shared generic token. That is
the ``Central Dispensary`` over-merge the `place` pack fixed by shipping a
table, and this is the same fix for organisations.

Source and licence
------------------
GLEIF (Global Legal Entity Identifier Foundation), Level 1 legal-entity
reference data, via the public API at https://api.gleif.org.

**CC0 1.0 Universal** — a public domain dedication. No attribution condition,
no share-alike, no commercial restriction.

GLEIF was built *first*, not exclusively. Only one alternative is actually
blocked, and the distinction between the two is the point:

* **Open Food Facts** is ODbL, and share-alike reaches *derived databases* — a
  frequency table built from its names is one, so vendoring it would oblige us
  to license the wheel's contents under ODbL. That is a real blocker.
* **Trase** (Ghanaian and Ivorian cocoa exporters) is **not blocked**. CC BY
  asks for attribution and places no condition on the licence of the work it
  travels in, and this repo already ships CC BY 4.0 data with attribution — see
  ``data/er_bench/SOURCES.md`` on the Leipzig sets. Trase is the natural second
  table, because it covers the population GLEIF demonstrably cannot: 51
  registered entities for the world's largest cocoa producer. Read the specific
  dataset's terms, since Trase licenses per dataset.

See ``SOURCES.md`` beside this file for the full comparison.

Known bias — read before quoting anything built on this
-------------------------------------------------------
LEI registration follows participation in financial markets, so coverage is
wildly uneven, and it is thinnest exactly where arche claims to be strong::

    Cote d'Ivoire      51        Netherlands   194,784
    Ghana             138        Germany       254,088
    Nigeria           978        Belgium        67,476
    Kenya             306        Switzerland     27,993
    Ethiopia           16
    10 W/E African countries combined: 1,743

Fifty-one entities for the world's largest cocoa producer. **This table
therefore knows corporate naming — that `Limited`, `Holdings`, `Central` and
`International` are common — and does not know West African cooperative
naming.** It is the right instrument for keeping a generic token from clearing
the gate, and the wrong instrument for any claim about African organisation
names. Those claims still need adjudicated African data, which does not exist
yet in this repo.

Sampling
--------
Two strata, and the split is deliberate:

1. **Census** of every LEI record in the listed African jurisdictions. They are
   small enough to take whole, so African naming is represented as fully as the
   source allows rather than left to a random draw that would return almost
   nothing.
2. **Shallow sample across many jurisdictions** — a few pages from each of ~45
   countries, rather than deep offsets into the global index.

   The first version sampled the global index at evenly spaced page offsets,
   reaching page numbers in the tens of thousands. Correct as a statistical
   design, bad as an engineering one: deep pagination makes the server count
   past every preceding row, so requests got slower the further in they went
   and the build never finished. Filtering by country keeps every request on
   the first few pages of a much smaller result set, and sampling many
   countries buys back the diversity the spread was for.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://api.gleif.org/api/v1/lei-records"
PAGE = 200
#: Taken whole — each is small, and a random draw would return almost none.
AFRICAN = ["GH", "CI", "NG", "KE", "ET", "TZ", "UG", "RW", "CM", "SN",
           "ZA", "BJ", "TG", "BF", "ML", "MW", "ZM", "ZW", "MZ", "MG"]
#: Sampled shallowly (first PAGES_PER_COUNTRY pages each) for diversity without
#: deep pagination. Spread across regions and legal traditions on purpose:
#: Anglophone, Francophone, Lusophone, Nordic, Gulf and Asian naming all
#: contribute different ordinary tokens.
SAMPLED = ["NL", "DE", "BE", "CH", "FR", "GB", "IE", "IT", "ES", "PT",
           "SE", "NO", "DK", "FI", "PL", "AT", "LU", "CZ", "GR", "RO",
           "US", "CA", "AU", "NZ", "JP", "SG", "HK", "IN", "MY", "ID",
           "BR", "MX", "AR", "CL", "CO", "PE", "AE", "SA", "TR", "IL",
           "CN", "KR", "TH", "VN", "PH"]
PAGES_PER_COUNTRY = 4

_HEADERS = {"Accept": "application/vnd.api+json",
            "User-Agent": "arche-dataops/0.4 (+https://unpatterned.org)"}


def _get(url: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _names(payload: dict) -> list[str]:
    """Every name form a record carries — legal name plus transliterations.

    Transliterations are included because they are the same population of
    strings a matcher will meet, and because a token that is common only in
    transliterated form is still common.
    """
    out: list[str] = []
    for rec in payload.get("data", []):
        entity = rec.get("attributes", {}).get("entity", {})
        legal = (entity.get("legalName") or {}).get("name")
        if legal:
            out.append(legal)
        for key in ("otherNames", "transliteratedOtherNames"):
            for alt in entity.get(key) or []:
                if isinstance(alt, dict) and alt.get("name"):
                    out.append(alt["name"])
    return out


def _census(country: str, names: Counter) -> int:
    got, page = 0, 1
    while True:
        url = (f"{API}?page%5Bsize%5D={PAGE}&page%5Bnumber%5D={page}"
               f"&filter%5Bentity.legalAddress.country%5D={country}")
        payload = _get(url)
        batch = _names(payload)
        if not batch:
            break
        names.update(batch)
        got += len(batch)
        total_pages = payload["meta"]["pagination"].get("lastPage", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.15)
    return got


def _apply_curated_layer(table, tokens_path: Path) -> dict:
    """Apply `organisation_tokens.yaml` over the measured counts.

    A corpus only knows the words that are in it. GLEIF is built from
    financial-market participants, so `farmers` appears once in 52,875
    organisation names and the measured table calls it *rare* — which would let
    two unrelated "X Farmers Cooperative Society" records clear the
    distinctiveness gate on that word alone. No amount of extra GLEIF fixes
    that, because GLEIF does not contain cooperatives. A person who has read a
    supplier list has to say it, and the YAML is where they say it.

    Exactly the reasoning behind `place_tokens.yaml`, which met the same
    failure with `PHC` at 4 occurrences in 51,022 Nigerian facility names.

    Returns a report of every token touched, which is printed and recorded so
    the curated half stays inspectable rather than baked in silently. Never
    *lowers* a measured count: this layer exists to say "commoner than the
    corpus thinks", never the reverse.
    """
    report: dict = {"pack": None, "generic": {}, "overrides": {}, "skipped": []}
    if not tokens_path.exists():
        print(f"  ! no curated pack at {tokens_path} — measured counts only",
              flush=True)
        return report
    try:
        import yaml
    except ImportError:
        print("  ! pyyaml unavailable — skipping the curated layer", flush=True)
        return report

    pack = yaml.safe_load(tokens_path.read_text(encoding="utf-8")) or {}
    report["pack"] = {"version": pack.get("version"),
                      "sha256": hashlib.sha256(
                          tokens_path.read_bytes()).hexdigest()[:16]}
    settings = pack.get("settings") or {}
    min_rel = float(settings.get("generic_min_rel_freq", 1.0e-3))
    counts = table._counts                                  # noqa: SLF001
    generic = [t for t in (str(t).strip().casefold()
                           for t in pack.get("generic_tokens") or []) if t]
    original = {t: float(counts.get(t, 0.0)) for t in generic}

    # Raising a token raises the corpus total too, which lowers every token's
    # *relative* frequency — including the ones just raised. Computing the floor
    # once against the pre-adjustment total therefore lands slightly under
    # target (83 tokens raised to 223 left them at 0.000934, not 0.001). Iterate
    # to a fixed point instead; it converges in a handful of passes because each
    # round adds strictly less than the last.
    floor = 0.0
    for _ in range(50):
        total = sum(counts.values()) or 1.0
        new_floor = min_rel * total
        if abs(new_floor - floor) < 1e-9:
            break
        floor = new_floor
        for tok in generic:
            if original[tok] < floor:
                counts[tok] = floor

    for tok in generic:
        if original[tok] >= floor:
            report["skipped"].append(tok)      # already common enough measured
        else:
            report["generic"][tok] = {"was": round(original[tok], 1),
                                      "now": round(float(counts[tok]), 1)}

    for entry in pack.get("frequency_overrides") or []:
        tok = str(entry.get("token", "")).strip().casefold()
        if not tok or "count" not in entry:
            continue
        before = float(counts.get(tok, 0.0))
        counts[tok] = float(entry["count"])
        report["overrides"][tok] = {"was": round(before, 1),
                                    "now": float(entry["count"]),
                                    "reason": entry.get("reason", "")}
    return report


def main() -> int:
    names: Counter[str] = Counter()

    # The cached corpus makes a curated-layer edit a seconds-long rebuild
    # instead of a 250-request re-fetch. Delete gleif_names.json.gz to force a
    # fresh pull.
    cache = Path(__file__).resolve().parent / "gleif_names.json.gz"
    if cache.exists() and "--refetch" not in sys.argv:
        with gzip.open(cache, "rt", encoding="utf-8") as fh:
            names.update(json.load(fh))
        print(f"using cached corpus: {len(names):,} distinct name forms "
              f"(--refetch to pull again)", flush=True)
        return _finish(names)

    print("stratum 1 - census of African jurisdictions", flush=True)
    afr = 0
    for country in AFRICAN:
        try:
            n = _census(country, names)
        except Exception as exc:                       # noqa: BLE001
            print(f"  {country}: FAILED ({type(exc).__name__}) — skipped")
            continue
        afr += n
        print(f"  {country}: {n:,}", flush=True)
        time.sleep(0.15)
    print(f"  African name forms: {afr:,}", flush=True)

    print(f"stratum 2 - shallow sample, {len(SAMPLED)} jurisdictions x "
          f"{PAGES_PER_COUNTRY} pages", flush=True)
    glob = 0
    for country in SAMPLED:
        for page in range(1, PAGES_PER_COUNTRY + 1):
            url = (f"{API}?page%5Bsize%5D={PAGE}&page%5Bnumber%5D={page}"
                   f"&filter%5Bentity.legalAddress.country%5D={country}")
            try:
                batch = _names(_get(url))
            except Exception as exc:                       # noqa: BLE001
                print(f"  {country} p{page}: FAILED ({type(exc).__name__})",
                      flush=True)
                break
            if not batch:
                break
            names.update(batch)
            glob += len(batch)
            time.sleep(0.1)
        print(f"  {country}: running total {glob:,}", flush=True)
    print(f"  sampled name forms: {glob:,}", flush=True)

    return _finish(names)


def _finish(names: Counter) -> int:
    if len(names) < 5_000:
        print(f"ERROR: only {len(names):,} distinct names collected; refusing to "
              "ship a table too thin to be a population claim.", file=sys.stderr)
        return 1

    # Cache the raw corpus next to the builder so the table can be rebuilt, and
    # audited, without re-fetching.
    out_dir = Path(__file__).resolve().parent
    raw = out_dir / "gleif_names.json.gz"
    with gzip.open(raw, "wt", encoding="utf-8") as fh:
        json.dump(dict(names), fh)
    print(f"raw corpus -> {raw} ({len(names):,} distinct name forms)")

    # `from_counts`, not `from_corpus`: only the former marks the table
    # population_scale, and that flag is what licenses the distinctive cap.
    # Keyed by full legal name throughout — one keying convention per call.
    sys.path.insert(0, str(out_dir.parents[1] / "packages" / "arche-core" / "src"))
    from arche.resolve._tokenfreq import TokenFrequencyTable

    table = TokenFrequencyTable.from_counts(dict(names))
    curated = (out_dir.parents[1] / "packages" / "arche-core" / "src" / "arche"
               / "resolve" / "_data" / "organisation_tokens.yaml")
    report = _apply_curated_layer(table, curated)
    assert table.population_scale, "table must be population-scale to be useful"

    dest = (out_dir.parents[1] / "packages" / "arche-core" / "src" / "arche"
            / "resolve" / "_data" / "organisation_frequencies.json.gz")
    table.save(dest)
    print(f"table -> {dest} ({dest.stat().st_size / 1024:.0f} KB)")

    # `_counts` is the private store; there is no public accessor, and this is
    # a build script in the same repo rather than a consumer of the library.
    common = Counter(dict(table._counts)).most_common(15)  # noqa: SLF001
    print("most common tokens:", ", ".join(f"{t}({int(c)})" for t, c in common))
    print(f"distinct tokens: {len(table._counts):,}")  # noqa: SLF001
    print(f"curated layer: pack {report['pack']} — "
          f"{len(report['generic'])} tokens raised, "
          f"{len(report['skipped'])} already common, "
          f"{len(report['overrides'])} overridden")
    for tok in ("cooperative", "farmers", "society", "central", "washing"):
        print(f"    {tok:12s} {int(table._counts.get(tok, 0)):>6}")  # noqa: SLF001
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
