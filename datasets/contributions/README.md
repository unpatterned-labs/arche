# Curated Contribution CSVs (v1)

Drop reviewer-prepared CSV files here for ingestion by:

```bash
python -m datasets.names_pipeline ingest_csv --append
```

Required columns (`CuratedContributionCSVV1`):

- `source`
- `source_id`
- `source_license`
- `name_raw`
- `name_type` (`given` or `family`)
- `country_iso2` (ISO-3166 alpha-2)
- `language_tag`
- `evidence_count` (integer >= 1)
- `fetched_at` (ISO datetime)

Optional columns:

- `canonical`
- `suggested_tradition`
- `reviewer_notes`
