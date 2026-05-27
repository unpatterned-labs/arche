---
language:
- en
- yo
- ig
- ha
- sw
- am
- ar
- fr
- pt
- so
- ti
- zu
- xh
- tn
- st
- lg
- mg
license: apache-2.0
task_categories:
- token-classification
- text-classification
tags:
- identity-resolution
- entity-resolution
- african-names
- cultural-naming
- name-matching
- record-linkage
- DPI
- digital-public-infrastructure
- deduplication
- NER
pretty_name: "African Cultural Naming Intelligence Dataset"
size_categories:
- n<1K
configs:
- config_name: default
  data_files:
  - split: full
    path: "data/african_naming_equivalences.csv"
source_datasets: []
---

# African Cultural Naming Intelligence Dataset

## Dataset Description

- **Homepage:** https://github.com/unpatterned-labs/archetree/main/datasets
- **Repository:** https://github.com/Plehthore/arche
- **Paper:** N/A
- **Point of Contact:** datasets@unpatterned.ai
- **License:** CC-BY-NC-SA 4.0
- **Size:** 114 equivalence groups, 454 name forms, 340 variant spellings

### Dataset Summary

The African Cultural Naming Intelligence Dataset is a curated, machine-readable collection of name equivalence groups spanning 20+ African ethnic and linguistic traditions. It maps canonical name forms to their regional, phonetic, diacritical, and transliteration variants as they appear across civil registration systems, health records, financial databases, and identity platforms on the African continent.

This is the first open dataset purpose-built for **identity resolution in African Digital Public Infrastructure (DPI)**. It addresses a critical gap: existing name-matching tools (Splink, Zingg, Senzing, Dedupe) rely on Anglo-centric edit-distance heuristics that fail on African naming patterns. "Mamadou Diallo" and "Muhammad Jallow" are the same person across a Francophone/Anglophone border, but no edit-distance algorithm will match them.

The dataset encodes the cultural knowledge needed to bridge that gap.

### Supported Tasks and Leaderboards

This is a **reference dataset**, not a training set. It supports:

- **Entity resolution / record linkage** -- improving match rates when deduplicating person records across African systems
- **Named entity recognition (NER)** -- providing cultural context for person name spans extracted from African-language text
- **Identity verification** -- matching names across civil registration (OpenCRVS), national ID (MOSIP), and health (DHIS2) systems
- **Cross-border identity matching** -- resolving naming differences introduced by colonial-era Francophone/Anglophone/Lusophone spelling conventions

No leaderboard is associated with this dataset. We welcome benchmark contributions that measure identity resolution accuracy improvements when incorporating this data.

### Languages

The dataset covers names from the following language families and traditions:

| Language / Tradition | ISO 639-1 | Region | Groups | Names |
|---|---|---|---|---|
| Arabic / Pan-Islamic | ar | Continent-wide | 19 | 140 |
| Yoruba | yo | Nigeria, Benin | 10 | 30 |
| Igbo | ig | Nigeria | 9 | 27 |
| Hausa | ha | Nigeria, Niger, Ghana | 5 | 18 |
| Fulani / Pulaar | -- | West Africa (cross-border) | 6 | 21 |
| Akan / Ghanaian | -- | Ghana | 6 | 18 |
| Wolof | wo | Senegal, Gambia | 4 | 15 |
| Swahili | sw | East Africa | 4 | 10 |
| Luo | -- | Kenya, Uganda, Tanzania | 5 | 15 |
| Amharic / Ethiopian | am | Ethiopia | 4 | 13 |
| Tigrinya | ti | Eritrea, Ethiopia | 4 | 12 |
| Somali | so | Somalia, Kenya, Ethiopia | 2 | 6 |
| Zulu / Xhosa | zu/xh | South Africa | 6 | 14 |
| Tswana / Sotho | tn/st | South Africa, Botswana | 5 | 13 |
| Amazigh / Berber | -- | North Africa | 3 | 11 |
| Congolese / Lingala | ln | DRC | 3 | 7 |
| Malagasy | mg | Madagascar | 2 | 5 |
| Cross-linguistic (colonial-era) | en/fr/pt | Continent-wide | 8 | 45 |

Names frequently contain diacritical marks from Yoruba tonal orthography (e.g., Adeyemi), French accents (e.g., Traore), and Arabic transliteration conventions (e.g., Aisha).

## Dataset Structure

### Data Instances

The dataset is organized as YAML files, one per regional tradition. Each file contains a list of equivalence groups:

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

When exported to tabular format (CSV/Parquet), each row represents one variant mapping:

| canonical | variant | tradition | file |
|---|---|---|---|
| Mohammed | Muhammad | Pan-Islamic / Arabic-origin names used across Africa | pan_islamic |
| Mohammed | Mohamed | Pan-Islamic / Arabic-origin names used across Africa | pan_islamic |
| Mohammed | Mamadou | Pan-Islamic / Arabic-origin names used across Africa | pan_islamic |
| Diallo | Jallow | West African names (Yoruba, Igbo, Hausa, Fulani, Akan, Wolof) | west_african |

### Data Fields

**YAML format (source of truth):**

- `tradition` (string): Top-level field describing the cultural/linguistic tradition for the file
- `groups` (list): List of equivalence group objects
  - `canonical` (string): The canonical (reference) form of the name. This is not necessarily "more correct" -- it is the most widely recognized spelling used as the lookup key.
  - `variants` (list of strings): Alternative spellings, transliterations, regional adaptations, and abbreviations of the canonical form. Every variant in a group is considered equivalent to every other variant, not just to the canonical form.

**Tabular export format (CSV/Parquet/JSONL):**

- `canonical` (string): The canonical form of the name
- `variant` (string): One variant spelling/adaptation
- `tradition` (string): The cultural/linguistic tradition label
- `file` (string): Source YAML file stem (e.g., `pan_islamic`, `west_african`)

### Data Splits

This is a reference/lookup dataset, not a train/test dataset. There is a single complete split:

| Split | Groups | Variants | Total Names |
|---|---|---|---|
| full | 114 | 340 | 454 |

## Dataset Creation

### Curation Rationale

African identity systems face a unique name-matching challenge. A single person may appear as:
- **Mamadou Diallo** in a Senegalese civil registration system (French orthography)
- **Muhammad Jallow** in a Gambian health record (English orthography)
- **Muhammadu Jalo** in a Nigerian voter roll (Hausa-influenced spelling)

These are not typos. They reflect systematic differences in how the same names are spelled across colonial-era language boundaries, regional phonetic conventions, and transliteration systems. No edit-distance algorithm will reliably match them.

This dataset was created to encode the cultural knowledge that African data clerks, civil registrars, and health workers carry in their heads -- and make it machine-readable for identity resolution pipelines.

### Source Data

#### Initial Data Collection and Normalization

Data was curated by domain experts with knowledge of African naming conventions, drawing from:

1. **Civil registration records** -- naming patterns observed in birth/death registration systems across West, East, and Southern Africa
2. **Linguistic references** -- published works on Yoruba orthography, Fulani/Pulaar naming conventions, Arabic transliteration standards, and Akan day-naming traditions
3. **DPI deployment experience** -- real-world name-matching challenges encountered in OpenCRVS, MOSIP, and DHIS2 deployments
4. **Community input** -- contributions from African software developers, data scientists, and civil registration practitioners

All names in the dataset are common given names and surnames. No individual person records were used in creating this dataset.

#### Who are the source language producers?

The naming conventions encoded in this dataset originate from living cultural and linguistic traditions practiced by hundreds of millions of people across Africa. The dataset was compiled by researchers and practitioners at unpatterned.ai with domain expertise in African naming systems.

### Annotations

This dataset does not contain annotations in the traditional NLP sense. Each equivalence group represents expert-curated knowledge about which name spellings refer to the same underlying name.

### Personal and Sensitive Information

This dataset contains **no personal data**. It consists entirely of common name forms (given names and surnames) that are shared by millions of people. No individual can be identified from this dataset. The names are cultural/linguistic patterns, not records of specific individuals.

## Considerations for Using the Data

### Social Impact

**Positive impacts:**
- Improves identity resolution accuracy for African populations, reducing exclusion from government services, healthcare, and financial systems
- Helps digital public infrastructure correctly match records for people whose names are systematically misspelled by Anglo-centric algorithms
- Supports the DPGA (Digital Public Goods Alliance) mission of equitable access to digital systems

**Risks to monitor:**
- Name equivalence data could theoretically be misused for surveillance; the CC-BY-NC-SA license and ethical review processes mitigate this
- Equivalence groups are not exhaustive -- absence from the dataset should not be treated as evidence that two names are NOT equivalent

### Discussion of Biases

- **Coverage bias**: The dataset currently has stronger coverage of West African (44 groups) and Pan-Islamic (19 groups) naming traditions than Central or Southern African traditions. This reflects the current state of curation, not the relative importance of these traditions.
- **Canonical form bias**: The choice of "canonical" form reflects common usage in English-language technical contexts and is not a judgment about which spelling is linguistically preferred.
- **Urban bias**: The dataset focuses on names most commonly encountered in identity systems, which may under-represent rural or hyper-local naming variants.
- **Gender representation**: Both male and female names are included, but the dataset has not been formally audited for gender balance.

### Other Known Limitations

- The dataset covers name equivalences only, not patronymic conventions, honorifics, clan names, or naming-ceremony practices that vary by ethnic group
- Diacritical variants are included where known, but the full space of possible diacritical combinations for Yoruba tonal marks, for example, is much larger than what is captured here
- Cross-linguistic (colonial-era) groups may overlap with tradition-specific groups (e.g., "Musa" appears in both Hausa and cross-linguistic contexts)

## Additional Information

### Dataset Curators

This dataset is maintained by [unpatterned.ai](https://unpatterned.ai), a non-profit research initiative focused on cognitive infrastructure for frontier systems.

### Licensing Information

This dataset is released under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC-BY-NC-SA 4.0)** license.

- **Non-commercial use** (academic research, government DPI deployments, non-profit projects, open-source DPI integrations): Free to use with attribution
- **Commercial use** (SaaS products, KYC/AML platforms, fintech deduplication): Requires a commercial license from unpatterned.ai

Contact licensing@unpatterned.ai for commercial licensing. Pricing is by deployment scale, not per-record, with generous terms for startups and African-headquartered companies.

### Citation Information

```bibtex
@misc{arche_naming_2026,
  title={African Cultural Naming Intelligence Dataset: Name Equivalence Groups for African Identity Resolution},
  author={unpatterned.ai},
  year={2026},
  howpublished={\url{https://huggingface.co/datasets/unpatterned/african-cultural-naming}},
  note={114 equivalence groups covering 454 name forms across 20+ African ethnic/linguistic traditions}
}
```

```
arche Cultural Naming Dataset: Name equivalence groups for 20+ African
ethnic naming traditions. unpatterned.ai, 2026.
https://huggingface.co/datasets/unpatterned/african-cultural-naming
```

### Contributions

We welcome contributions, especially for underrepresented traditions. See the [contribution guide](https://github.com/unpatterned-labs/archetree/main/datasets#contributing) for instructions.

Priority areas for expansion:
- Central African naming traditions (Kinyarwanda, Kirundi, Lingala)
- Cushitic naming traditions (Oromo, Afar)
- Nilotic naming traditions (Dinka, Nuer, Maasai)
- Khoisan naming traditions
- Additional Bantu traditions (Shona, Chewa, Bemba, Luganda)
