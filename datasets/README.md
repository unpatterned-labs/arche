# African Cultural Naming Intelligence Dataset

**The first comprehensive, machine-readable dataset of African naming equivalences for identity resolution.**

Published by [unpatterned.org](https://unpatterned.org) under [Apache 2.0](DATASET_LICENSE.md).

Available on HuggingFace: [unpatterned/african-cultural-naming](https://huggingface.co/datasets/unpatterned/african-cultural-naming)

## What This Is

A curated, community-maintained dataset that encodes:

- **114 naming equivalence groups** across **454 name forms** and **340 variant spellings**
- **20+ ethnic/linguistic traditions** -- Pan-Islamic, Yoruba, Igbo, Hausa, Fulani, Akan, Wolof, Swahili, Luo, Amharic, Tigrinya, Somali, Zulu, Xhosa, Tswana, Sotho, Amazigh, Congolese, Malagasy, and more
- **Colonial-era cross-linguistic adaptations** -- Pierre = Peter = Petros, Jean = John = Yohana
- **Diacritical normalization** -- Kone = Kone, Traore = Traore, Adeyemi = Adeyemi (Yoruba tonal marks, French accents, Arabic transliterations)

## Why This Matters

"Mamadou Diallo" and "Muhammad Jallow" are the same person across a Francophone/Anglophone border. No edit-distance algorithm will match them. This dataset encodes the cultural knowledge that makes that match possible.

## Structure

```
datasets/
├── name_equivalences/         # Source of truth — curated YAML
│   ├── pan_islamic.yaml       # 19 groups, 140 names (Mohammed, Fatima, Ibrahim, ...)
│   ├── west_african.yaml      # 44 groups, 149 names (Yoruba, Igbo, Hausa, Fulani, Akan, Wolof)
│   ├── east_african.yaml      # 21 groups, 63 names (Swahili, Luo, Amharic, Tigrinya, Somali)
│   ├── southern_african.yaml  # 14 groups, 35 names (Zulu, Xhosa, Tswana, Sotho)
│   ├── north_african.yaml     # 8 groups, 22 names (Amazigh, Congolese, Malagasy)
│   └── cross_linguistic.yaml  # 8 groups, 45 names (colonial-era adaptations)
├── contributions/             # Manual name contributions (CSV)
│   ├── LABELING_GUIDE.md      # Step-by-step labeling instructions
│   ├── benin_edo_names.csv    # Benin/Edo name contributions
│   └── sample_curated_contribution.csv
├── names_dataops/             # Data pipeline (Wikidata + CSV → YAML)
│   ├── wikidata.py            # Wikidata SPARQL fetcher
│   ├── normalize.py           # Unicode normalization
│   ├── schemas.py             # Pydantic validation schemas
│   ├── cli.py                 # DataOps CLI
│   └── ...
├── data/                      # Generated exports (CSV, JSONL, Parquet)
├── compliance/                # Jurisdiction-specific compliance metadata
├── DATACARD.md                # HuggingFace dataset card
├── DATASET_LICENSE.md         # CC-BY-NC-SA 4.0 license
├── STATISTICS.md              # Detailed dataset statistics
├── export_hf.py               # Export to CSV / JSONL / Parquet for HuggingFace
└── README.md                  # This file
```

## YAML Format

Each file contains a list of equivalence groups:

```yaml
tradition: Pan-Islamic / Arabic-origin names used across Africa
groups:
- canonical: Mohammed
  variants:
  - Muhammad
  - Mohamed
  - Muhammed
  - Muhammadu
  - Mamadou
  - Mahamadou
  - Mohammadu
  - Mohamad
  - Mouhamed
  - Mahamed
  - Mamadu
  - Mohd
  - Md
```

## Quick Start




```
# Implemented. You now get live logs while it runs.
uv run python -m datasets.build_african_names --include-csv

uv run python -m datasets.build_african_names --countries NG --max-pages 1 --page-limit 50


uv run python -m datasets.build_african_names --include-csv --page-limit 5000 --max-pages 12
```

### Load with HuggingFace Datasets

```python
from datasets import load_dataset

ds = load_dataset("unpatterned/african-cultural-naming")
print(ds["full"][0])
# {'canonical': 'Mohammed', 'variant': 'Muhammad', 'tradition': 'Pan-Islamic / ...', 'file': 'pan_islamic'}
```

### Load with the arche SDK

```python
from arche.african.names import are_names_equivalent

match, confidence = are_names_equivalent("Mamadou Diallo", "Muhammad Jallow")
print(f"Match: {match}, Confidence: {confidence}")
# Match: True, Confidence: 0.90
```

### Load directly from YAML (no dependencies)

```python
import yaml

with open("datasets/name_equivalences/pan_islamic.yaml") as f:
    data = yaml.safe_load(f)

for group in data["groups"]:
    print(f"{group['canonical']}: {', '.join(group['variants'])}")
```

### Export to tabular formats

```bash
# Export to CSV, JSONL, and Parquet
python datasets/export_hf.py

# Output:
#   datasets/data/african_naming_equivalences.csv
#   datasets/data/african_naming_equivalences.jsonl
#   datasets/data/african_naming_equivalences.parquet  (if pyarrow installed)
```

### Build African names lexicon (simple path)

```bash
# Fetch + clean + union + dedupe names from the core 16 countries
python -m datasets.build_african_names --include-csv
```

The Wikidata fetch now combines:
- person-derived names (`human` + citizenship + given/family properties)
- direct name entities (`given name`/`family name` classes, including first-name subclasses)

Outputs for arche are written to:

- `datasets/data/african_names_lexicon_v1.csv`
- `datasets/data/african_names_lexicon_v1.jsonl`
- `datasets/data/african_names_unique_v1.csv` (minimal columns: `name`, `name_type`)
- `datasets/data/african_names_unique_v1.jsonl`

Optional: regenerate schema docs

```bash
python -m datasets.names_pipeline generate_schema_docs
```

Output JSON schemas are written to `datasets/schemas/`.

### GitHub Actions automation

- `.github/workflows/names_ingest.yml`: scheduled/manual lexicon build and artifact upload.
- `.github/workflows/names_validate.yml`: PR validation for schema contracts, determinism, and tests.
- `.github/workflows/names_publish_hf.yml`: manual release gate for lexicon + enriched exports to Hugging Face.

## Usage

This dataset can be used by any entity resolution tool -- Splink, Zingg, Senzing, Dedupe, or your own custom pipeline. The [arche SDK](https://github.com/Plehthore/arche) loads these automatically.

Typical integration patterns:
1. **Pre-processing**: Normalize names using the equivalence groups before running Splink/Dedupe comparison vectors
2. **Blocking**: Use canonical forms as blocking keys to reduce the comparison space
3. **Scoring**: Add an equivalence-match feature to your Splink model settings
4. **Post-processing**: Flag potential matches that edit-distance alone would miss

## Contributing Names

We welcome contributions, especially for underrepresented traditions. There are two ways to contribute:

### Option A: CSV Contributions (Recommended)

The easiest way to add names. See **[contributions/LABELING_GUIDE.md](contributions/LABELING_GUIDE.md)** for the full step-by-step process.

Quick version:

1. Create a CSV file in `datasets/contributions/` following this format:

```csv
source,source_id,source_license,name_raw,name_type,country_iso2,language_tag,evidence_count,fetched_at,canonical,suggested_tradition,reviewer_notes
manual_csv,edo-001,CC-BY-4.0,Irorere,family,NG,ed,1,2026-04-19T00:00:00+00:00,Irorere,west_african,"Benin/Edo name meaning 'I'm thinking about it'"
manual_csv,edo-002,CC-BY-4.0,Osaro,given,NG,ed,1,2026-04-19T00:00:00+00:00,Osaro,west_african,"Benin/Edo name meaning 'God's gift'"
manual_csv,edo-003,CC-BY-4.0,Osarobo,given,NG,ed,1,2026-04-19T00:00:00+00:00,Osaro,west_african,"Variant of Osaro"
```

2. Names sharing the same `canonical` value become equivalences (Osaro = Osarobo)
3. Include meanings in `reviewer_notes` — invaluable for documentation
4. Run the ingest pipeline:

```bash
uv run python -m datasets.names_dataops.cli ingest_csv \
    --input-dir datasets/contributions/ \
    --output datasets/data/raw_name_evidence_v1.jsonl \
    --append
```

See [benin_edo_names.csv](contributions/benin_edo_names.csv) for a complete example with Benin/Edo names.

### Option B: Direct YAML Editing

1. Fork the [repository](https://github.com/Plehthore/arche)
2. Add entries to the appropriate YAML file in `datasets/name_equivalences/`
3. Follow the existing format: `canonical` + `variants` list
4. Submit a pull request with a brief note explaining the naming tradition

### Using the arche Level 2 API to Verify

After adding names, test your contributions with arche's `match()` function:

```python
from arche import match

# Test equivalences you defined
score = match("Osaro", "Osarobo")
print(score)  # MatchScore with cultural equivalence

# Test with jurisdiction priors
score = match(
    {"name": "Nosakhare Irorere", "phone": "+234 802 123 4567"},
    {"name": "Nosakhere Irorere", "phone": "08021234567"},
    jurisdiction="NG",
)
print(score)  # → MatchScore(score=1.0, decision='match')
```

### Priority Areas for Expansion

- **Benin/Edo**: Edo, Esan, Etsako, Owan names (NG)
- **Central African**: Kinyarwanda, Kirundi, Lingala
- **Cushitic**: Oromo, Afar
- **Nilotic**: Dinka, Nuer, Maasai
- **Khoisan** traditions
- **Additional Bantu**: Shona, Chewa, Bemba, Luganda
- **Ijaw/Niger Delta**: Ijaw, Urhobo, Itsekiri names (NG)

### Contribution Guidelines

- Each equivalence group should have at least one canonical form and one variant
- Preserve diacritical marks where they are part of the standard orthography
- Do not add individual person names -- only common name forms shared by many people
- Include both male and female names
- Include meanings in `reviewer_notes` when known — these enrich the dataset
- If a name appears in multiple traditions (e.g., "Musa" in Hausa and cross-linguistic), place it in the most specific tradition file

## Citation

```bibtex
@misc{arche_naming_2026,
  title={African Cultural Naming Intelligence Dataset: Name Equivalence Groups for African Identity Resolution},
  author={unpatterned.ai},
  year={2026},
  howpublished={\url{https://huggingface.co/datasets/unpatterned/african-cultural-naming}},
  note={114 equivalence groups covering 454 name forms across 20+ African ethnic/linguistic traditions}
}
```

## License

[Apache 2.0](DATASET_LICENSE.md) — free for any use, commercial or non-commercial. Attribution required.

The naming equivalence data encodes public cultural knowledge. We open-source it under Apache 2.0 to maximize adoption and to become the standard for cultural naming intelligence in identity resolution. The ongoing curation effort — funded by the community and by [Plehthore](https://plehthore.com) — is what makes this dataset grow.

See [DATASET_LICENSE.md](DATASET_LICENSE.md) for full terms.
