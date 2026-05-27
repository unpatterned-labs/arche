# Name Labeling & Contribution Guide

Step-by-step process for adding names, equivalences, and cultural naming data to arche's identity intelligence engine.

## Overview

arche's naming intelligence comes from two sources:

1. **Wikidata** — automated extraction of names by country (thousands of names)
2. **Manual contributions** — curated CSV files with cultural knowledge that Wikidata doesn't capture (meanings, equivalences, ethnic traditions)

This guide covers how to contribute manually. Your contributions flow through the pipeline:

```
Your CSV → ingest → normalize → generate candidates → review → YAML → arche model
```

---

## Step 1: Understand the CSV Format

Every contribution is a CSV file dropped into `datasets/contributions/`. The schema:

| Column | Required | Type | Description |
|---|---|---|---|
| `source` | Yes | string | Always `manual_csv` for manual contributions |
| `source_id` | Yes | string | Unique ID, format: `{tradition}-{number}` (e.g., `edo-001`) |
| `source_license` | Yes | string | Always `CC-BY-4.0` for contributions |
| `name_raw` | Yes | string | The name exactly as written (preserve diacritics) |
| `name_type` | Yes | `given` or `family` | Is this a first name or a surname? |
| `country_iso2` | Yes | 2-letter code | Country code: `NG`, `GH`, `KE`, `ZA`, `SN`, etc. |
| `language_tag` | Yes | string | Language/ethnic tag: `en`, `yo`, `ig`, `ha`, `ed`, `fr`, etc. |
| `evidence_count` | Yes | integer | How many times you've seen this name (minimum 1) |
| `fetched_at` | Yes | ISO datetime | Date of contribution: `2026-04-19T00:00:00+00:00` |
| `canonical` | Optional | string | The "primary" form if this is a variant (see Step 3) |
| `suggested_tradition` | Optional | string | Tradition group: `west_african`, `pan_islamic`, `east_african`, etc. |
| `reviewer_notes` | Optional | string | Meaning, context, ethnic group, anything useful |

### Language Tags

| Tag | Language/Group | Countries |
|---|---|---|
| `en` | English | NG, GH, KE, ZA, ... |
| `yo` | Yoruba | NG |
| `ig` | Igbo | NG |
| `ha` | Hausa | NG, NE, GH |
| `ed` | Edo/Benin | NG |
| `ij` | Ijaw | NG |
| `ak` | Akan/Twi | GH |
| `sw` | Swahili | KE, TZ, UG |
| `am` | Amharic | ET |
| `ar` | Arabic | EG, MA, SD, NG |
| `fr` | French | SN, CI, CM, ML |
| `zu` | Zulu | ZA |
| `xh` | Xhosa | ZA |
| `so` | Somali | SO, KE |
| `wo` | Wolof | SN |
| `ff` | Fulani/Fulfulde | NG, SN, ML, GN |

### Tradition Groups

| Tradition | Use For |
|---|---|
| `west_african` | Yoruba, Igbo, Hausa, Edo/Benin, Ijaw, Akan, Wolof, Fulani |
| `pan_islamic` | Arabic-origin names used across Africa |
| `east_african` | Swahili, Luo, Amharic, Tigrinya, Somali |
| `southern_african` | Zulu, Xhosa, Tswana, Sotho |
| `north_african` | Amazigh/Berber, Egyptian, Maghreb |
| `cross_linguistic` | Colonial-era adaptations (Pierre=Peter, Jean=John) |

---

## Step 2: Add New Names

To add names that arche doesn't know about yet, create a CSV with one row per name.

**Example — Adding Benin/Edo names:**

```csv
source,source_id,source_license,name_raw,name_type,country_iso2,language_tag,evidence_count,fetched_at,canonical,suggested_tradition,reviewer_notes
manual_csv,edo-001,CC-BY-4.0,Irorere,family,NG,ed,1,2026-04-19T00:00:00+00:00,Irorere,west_african,"Benin/Edo name meaning 'I'm thinking about it'"
manual_csv,edo-002,CC-BY-4.0,Aibuedfe,family,NG,ed,1,2026-04-19T00:00:00+00:00,Aibuedfe,west_african,"Benin/Edo name meaning 'you won't know when you become rich'"
manual_csv,edo-003,CC-BY-4.0,Osaro,given,NG,ed,1,2026-04-19T00:00:00+00:00,Osaro,west_african,"Benin/Edo name meaning 'God's gift'"
```

**Tips:**
- One row = one name form. If a name has variants, each variant gets its own row.
- `source_id` must be unique across your CSV file.
- Keep `evidence_count` at 1 unless you've personally verified the name in multiple real records.
- Put the meaning in `reviewer_notes` — this is invaluable for future documentation.

---

## Step 3: Define Equivalences

Equivalences tell arche that two names refer to the same person. The key is the `canonical` field — names that share the same `canonical` value are equivalents.

**Example — Osaro and its variants:**

```csv
source,source_id,source_license,name_raw,name_type,country_iso2,language_tag,evidence_count,fetched_at,canonical,suggested_tradition,reviewer_notes
manual_csv,edo-003,CC-BY-4.0,Osaro,given,NG,ed,1,2026-04-19T00:00:00+00:00,Osaro,west_african,"Primary form"
manual_csv,edo-004,CC-BY-4.0,Osarobo,given,NG,ed,1,2026-04-19T00:00:00+00:00,Osaro,west_african,"Variant of Osaro"
```

Both rows have `canonical=Osaro`, so arche will know Osaro = Osarobo.

**How equivalences map to YAML:**

Your CSV entries with `canonical=Osaro`:
```
Osaro (canonical=Osaro) + Osarobo (canonical=Osaro)
```

Become this YAML group:
```yaml
- canonical: Osaro
  variants:
  - Osarobo
```

**Cross-ethnic equivalences** — when the same name appears across ethnic groups:

```csv
manual_csv,islam-ng-001,CC-BY-4.0,Musa,given,NG,ha,3,2026-04-19T00:00:00+00:00,Musa,pan_islamic,"Hausa form of Moses"
manual_csv,islam-gh-001,CC-BY-4.0,Moussa,given,GH,ak,2,2026-04-19T00:00:00+00:00,Musa,pan_islamic,"Akan/Francophone form"
manual_csv,islam-sn-001,CC-BY-4.0,Moussa,given,SN,wo,2,2026-04-19T00:00:00+00:00,Musa,pan_islamic,"Wolof form"
```

All three share `canonical=Musa`, so arche will resolve Musa = Moussa across Nigeria, Ghana, and Senegal.

---

## Step 4: Validate Your CSV

Before submitting, validate that your CSV matches the schema:

```bash
# Validate your contribution file
uv run python -m datasets.names_dataops.cli validate_schema \
    --schema curated_csv \
    --input datasets/contributions/your_file.csv
```

If validation fails, it will tell you which row and column has the error.

---

## Step 5: Ingest Into the Pipeline

```bash
# Ingest your CSV into the raw evidence store
uv run python -m datasets.names_dataops.cli ingest_csv \
    --input-dir datasets/contributions/ \
    --output datasets/data/raw_name_evidence_v1.jsonl \
    --append

# Normalize the evidence
uv run python -m datasets.names_dataops.cli normalize \
    --input datasets/data/raw_name_evidence_v1.jsonl \
    --output datasets/data/normalized_names_v1.jsonl

# Generate equivalence candidates for review
uv run python -m datasets.names_dataops.cli generate_candidates \
    --input datasets/data/normalized_names_v1.jsonl \
    --yaml-dir datasets/name_equivalences/

# Build the lexicon
uv run python -m datasets.names_dataops.cli build_lexicon --include-csv
```

---

## Step 6: Verify in arche

After ingesting, verify your names work in arche:

```python
from arche import match

# Test that your new equivalences are recognized
score = match("Osaro", "Osarobo")
print(score)  # Should show high similarity if equivalence was added

# Test cultural name matching
score = match("Nosakhare", "Nosakhere")
print(score)  # Should show high score (spelling variant)
```

---

## Working with Wikidata

### Fetching Names from Wikidata

arche can automatically pull names from Wikidata for any country:

```bash
# Fetch names for Nigeria
uv run python -m datasets.names_dataops.cli fetch_wikidata \
    --output datasets/data/raw_name_evidence_v1.jsonl

# Or use the all-in-one build command
uv run python -m datasets.names_dataops.cli build_lexicon \
    --include-csv \
    --page-limit 5000 \
    --max-pages 6
```

### What Wikidata Gives vs. What Manual Labels Add

| | Wikidata | Manual CSV |
|---|---|---|
| **Volume** | Thousands of names per country | Tens to hundreds per contribution |
| **Name forms** | Names as they appear on Wikipedia | Names as they appear in real life |
| **Equivalences** | No (just individual names) | Yes (canonical + variant mapping) |
| **Meanings** | No | Yes (in reviewer_notes) |
| **Ethnic tradition** | Sometimes (via language) | Always (suggested_tradition) |
| **Spelling variants** | Sometimes (via aliases) | Yes (each variant is explicit) |
| **Informal forms** | Rarely | Yes (diminutives, nicknames) |

**Wikidata is breadth. Manual labels are depth.** Both are needed.

### How Wikidata Names Become Equivalences

1. Wikidata gives us raw names: "Mamadou" (SN), "Mohamed" (NG), "Mohammed" (KE)
2. The pipeline generates **candidate pairs** using phonetic similarity
3. A human reviewer approves or rejects each pair via the review CSV
4. Approved pairs become YAML equivalence groups

---

## File Naming Convention

Name your CSV files by tradition/ethnic group:

```
datasets/contributions/
├── benin_edo_names.csv           # Edo/Benin names
├── yoruba_names.csv              # Yoruba names
├── igbo_names.csv                # Igbo names
├── hausa_names.csv               # Hausa names
├── akan_names.csv                # Akan/Twi names (Ghana)
├── swahili_names.csv             # Swahili names (East Africa)
├── zulu_xhosa_names.csv          # Zulu/Xhosa names (South Africa)
├── francophone_west_africa.csv   # French-speaking West Africa
└── pan_islamic_additions.csv     # Cross-African Islamic names
```

---

## Quick Reference: Common Patterns

### Pattern 1: Name with no equivalents (just adding to lexicon)
```csv
manual_csv,edo-001,CC-BY-4.0,Irorere,family,NG,ed,1,2026-04-19T00:00:00+00:00,Irorere,west_african,"Meaning: 'I'm thinking about it'"
```

### Pattern 2: Name with spelling variants
```csv
manual_csv,edo-003,CC-BY-4.0,Nosakhare,given,NG,ed,1,2026-04-19T00:00:00+00:00,Nosakhare,west_african,"Primary spelling"
manual_csv,edo-004,CC-BY-4.0,Nosakhere,given,NG,ed,1,2026-04-19T00:00:00+00:00,Nosakhare,west_african,"Variant spelling"
manual_csv,edo-005,CC-BY-4.0,Nosa,given,NG,ed,1,2026-04-19T00:00:00+00:00,Nosakhare,west_african,"Short form / diminutive"
```

### Pattern 3: Cross-ethnic equivalence
```csv
manual_csv,cross-001,CC-BY-4.0,Chukwu,given,NG,ig,2,2026-04-19T00:00:00+00:00,God_theophoric,cross_linguistic,"Igbo theophoric root (God)"
manual_csv,cross-002,CC-BY-4.0,Osa,given,NG,ed,2,2026-04-19T00:00:00+00:00,God_theophoric,cross_linguistic,"Edo theophoric root (God)"
```

### Pattern 4: Name with meaning only (no equivalence)
```csv
manual_csv,edo-010,CC-BY-4.0,Aibuedfe,family,NG,ed,1,2026-04-19T00:00:00+00:00,,west_african,"Meaning: 'you won't know when you become rich'"
```
(Leave `canonical` empty if there's no equivalence to define)

---

## Future: Labeling Tool

We plan to build a dedicated labeling interface that replaces the CSV workflow:

- Web UI for reviewing candidate equivalences
- Side-by-side name comparison with phonetic analysis
- Batch approve/reject with confidence scoring
- Google Sheets integration for distributed review teams
- Direct push to YAML + HuggingFace

Until then, CSV contributions are the primary input method. The schema is stable and will be supported by the future tool.
