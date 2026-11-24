# `arche/_data/` — Vendored data assets

This directory holds vendored data assets that ship with `arche-core`. Each
asset is documented below with source, version, fetch date, and license.

The data is loaded at module-import time (small, fast) and used to satisfy
lookups that would otherwise require network calls. The lightweight-by-default
commitment (BP §7) is the reason: `pip install arche-core` and any code path
that touches country metadata works fully offline.

---

## `restcountries-v3.1-snapshot.json`

| Field | Value |
|---|---|
| Source | https://restcountries.com/v3.1/all |
| Fields requested | `cca2,cca3,name,idd,currencies,languages,capital,region,subregion,borders` (10-field API limit) |
| Fetch date | 2026-05-20 |
| Countries | 250 (59 African) |
| File size | ~116 KB |
| Project license | restcountries.com → Mozilla Public License 2.0 (https://gitlab.com/restcountries/restcountries) |
| arche use | Phone calling-code prefixes (`+234` for NG, etc.), currency codes by country, language inference, jurisdiction borders fallback, region/subregion filtering |
| Refresh policy | Manual. Refresh quarterly or on confirmed data change. Run `scripts/refresh-restcountries.sh` (TODO) to re-fetch. |
| Consumer | `arche.jurisdictions.restcountries` |

**Why vendored:** The live API caps `fields` at 10, rate-limits aggressively,
and is centrally hosted. A production arche-core deployment in rural Ethiopia
or running offline on a field tablet cannot depend on it. The snapshot is
small enough to ship in the wheel and refresh on demand.

**Refresh command:**

```bash
curl -sf "https://restcountries.com/v3.1/all?fields=cca2,cca3,name,idd,currencies,languages,capital,region,subregion,borders" \
  -o packages/arche-core/src/arche/_data/restcountries-v3.1-snapshot.json
```

After refreshing, bump the fetch date in this file and verify
`test_restcountries.py` still passes.

---

## `african_names_v1.jsonl.gz`

| Field | Value |
|---|---|
| Source | `datasets/data/african_names_unique_v1.jsonl` (arche DataOps export, derived from Wikidata / ParaNames) |
| Rows | 13,342 names (`{"name", "name_type": "given" \| "family"}`) |
| File size | ~55 KB gzipped |
| License | CC-BY-4.0 — credit *Unpatterned Labs*, <https://github.com/unpatterned-labs/arche> (see `datasets/DATASET_LICENSE.md`) |
| arche use | `arche.detect.names` (`PII-1-NAME` detection, `person_spans`) and the `PERSON` rule of the regex extractor |
| Refresh policy | Regenerate from the DataOps export when it changes; the loader prefers a repository export over this copy |
| Consumer | `arche.detect._names.lexicon._find_lexicon_path` (last fallback) |

**Why vendored:** the installed package used to detect 118 names — the
equivalence-group starter set — and nothing else. The 13k lexicon existed only
as a file in the source tree. Loaded lazily, on the first detection call.

---

## `hipaa_restricted_zip3.csv`

| Field | Value |
|---|---|
| Source | US HHS OCR, *Guidance Regarding Methods for De-identification of PHI*, <https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html> |
| Census basis | 2000 Census, as published by HHS ("three-digit ZIP codes [that] contain 20,000 or fewer persons") |
| Recorded | 2026-11-20 (hhs.gov refused automated fetches that day; checked against a secondary copy, cited in the file header) |
| Rows | 17 ZIP3 prefixes |
| License | US government work, public domain (17 U.S.C. §105) |
| arche use | HIPAA Safe Harbor 3-digit-ZIP rule: `generalize` on `PII-4-ZIP` keeps the ZIP3, or writes `000` for a listed prefix |
| Refresh policy | Manual. The rule refers to current Census data; replace with a ZCTA3 population table when HHS or Census publishes a newer list |
| Consumer | `arche.detect.us.zip.safe_harbor_zip3` |

## `detect/_names/common_names_v1.txt` (lives beside the name lexicon, listed here for provenance)

| Field | Value |
|---|---|
| What | 9,163 given-name and surname tokens added to the rules-only name detector (20 Nov 2026) |
| Sources | US Census Bureau 2010 surnames, top 3,000 (a US government work: public domain, 17 U.S.C. §105); `datasets/data/wikidata_name_pairs.jsonl` in this repository (8,156 given + family name pairs from ZA, NG, GH, KE and 7 other countries; Wikidata, CC0 — see `WIKIDATA_DATACARD.md`) |
| Rebuild | the file's own header says how |
| Not used | the SSA baby-names list (refused automated download); a fresh Wikidata query (rate-limited) |
| Caveat | some benchmark held-out names are now in this list, so the benchmark's held-out name pool is no longer fully held out |

---

## `places_v1.json.gz`

| Field | Value |
|---|---|
| Source | GeoNames, https://www.geonames.org/ (`cities1000.txt`, `admin1CodesASCII.txt`, `NG.txt`, `KE.txt`, `GH.txt` from https://download.geonames.org/export/dump/) |
| Fetch date | 2026-11-24 (the source files' sha256 are recorded in the file's `built_from`) |
| Contents | Folded place names, grouped by kind and rank: towns of 5,000+ everywhere; every state, region, county and province; for Nigeria, Kenya and Ghana every populated place, the areas within towns, and the second- and third-level divisions, with ASCII alternate names. No coordinates, no ids. |
| File size | ~600 KB (about 16 MB in memory once loaded, on first use) |
| License | Creative Commons Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/). Contains data from GeoNames; the names are folded and grouped, not otherwise changed. |
| arche use | Whether some words name a town, and how large a one, so the address parser can split "22 Ajala Road Ibadan" and read "Kumasi Kanyiri" larger to smaller |
| Consumer | `arche.addr.places` |

**Refresh command** (after downloading the five files into one directory, keeping
`cities1000/`, `NG/`, `KE/`, `GH/` as the zips unpack):

```bash
python data/scripts/build_places_geonames.py <geonames-dir>
```
