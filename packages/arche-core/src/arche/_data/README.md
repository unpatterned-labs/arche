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
