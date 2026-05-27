# Naming DataOps Schemas

These JSON Schema files are generated from the Pydantic v1 pipeline contracts:

- `raw_v1.schema.json`
- `normalized_v1.schema.json`
- `candidate_v1.schema.json`
- `curated_csv_v1.schema.json`
- `published_v1.schema.json`
- `lexicon_v1.schema.json`

Regenerate with:

```bash
python -m datasets.names_pipeline generate_schema_docs
```
