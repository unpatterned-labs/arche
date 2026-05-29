# How to Match African Names

```python
from arche.african.names import are_names_equivalent

match, confidence = are_names_equivalent("Mamadou", "Muhammad")
print(f"Match: {match}, Confidence: {confidence:.0%}")
# Match: True, Confidence: 88%
```

---

## Why this matters

800 million people across Africa have names that follow cultural naming conventions unfamiliar to Western identity systems. "Mamadou" (Fulani/Mandinka), "Muhammad" (Arabic), "Mohammed" (English transliteration), and "Muhammadu" (Hausa) are all the same name -- but string matching scores them at 60-70% similarity, below most matching thresholds.

This causes real harm: duplicate health records, failed KYC checks, broken social protection disbursements, and fragmented civil registration.

arche solves this with 114 cultural naming equivalence groups spanning 50+ ethnic traditions.

---

## Example pairs

```python
from arche.african.names import are_names_equivalent

pairs = [
    # Pan-Islamic naming traditions
    ("Fatima", "Fatoumata"),         # Arabic → Mandinka/Fulani
    ("Abdullahi", "Abdoulaye"),      # Arabic → French West African
    ("Ibrahim", "Ibrahima"),         # Arabic → Wolof/Mandinka
    ("Musa", "Moussa"),             # Arabic → French West African
    ("Aisha", "Aissatou"),          # Arabic → Fulani
    # Fulani cross-ethnic
    ("Diallo", "Jallow"),           # Fulani name, different spellings by country
    # Colonial-era European equivalences
    ("Pierre", "Peter"),            # French → English (common in Cameroon, DRC)
    # Yoruba naming
    ("Oluwaseun", "Seun"),          # Full Yoruba → shortened form
    # Different people (negative case)
    ("Janet Okafor", "David Mensah"),
]

for name1, name2 in pairs:
    match, conf = are_names_equivalent(name1, name2)
    status = "MATCH" if match else "NO MATCH"
    print(f"  {name1:20} ~ {name2:20} → {status} ({conf:.0%})")
```

Output:

```
  Fatima               ~ Fatoumata            → MATCH (94%)
  Abdullahi            ~ Abdoulaye            → MATCH (87%)
  Ibrahim              ~ Ibrahima             → MATCH (91%)
  Musa                 ~ Moussa               → MATCH (96%)
  Aisha                ~ Aissatou             → MATCH (89%)
  Diallo               ~ Jallow               → MATCH (90%)
  Pierre               ~ Peter                → MATCH (91%)
  Oluwaseun            ~ Seun                 → MATCH (85%)
  Janet Okafor         ~ David Mensah         → NO MATCH (12%)
```

---

## How it works

`are_names_equivalent()` uses a weighted combination of two techniques:

1. **Equivalence-table lookup** (60% weight) -- checks if any name token belongs to the same equivalence group as a token in the other name. The equivalence data is stored in YAML files under `datasets/name_equivalences/`.

2. **Jaro-Winkler similarity** (40% weight) -- character-level fuzzy match on the full normalized strings, catching transliteration variants not in the table.

The combined score must exceed a threshold (default 0.80) to return `True`.

```python
from arche.african.names import are_names_equivalent

# Adjust the threshold
match, conf = are_names_equivalent("Fatima", "Fatoumata", threshold=0.70)

# Adjust the weighting
match, conf = are_names_equivalent(
    "Fatima", "Fatoumata",
    equivalence_weight=0.80,  # Trust the table more
    jaro_weight=0.20,
)
```

Parameters:

| Parameter | Default | Description |
|---|---|---|
| `name1`, `name2` | (required) | Names to compare |
| `equivalence_weight` | `0.60` | Weight for equivalence-table lookup |
| `jaro_weight` | `0.40` | Weight for Jaro-Winkler similarity |
| `threshold` | `0.80` | Minimum combined score to return `True` |

---

## The 114 equivalence groups

The equivalence data covers:

| Category | Examples | Groups |
|---|---|---|
| Pan-Islamic | Muhammad/Mamadou/Mohammed/Muhammadu | ~30 |
| Fulani/Pulaar | Diallo/Jallow/Jaloh, Ba/Bah | ~15 |
| Yoruba | Oluwaseun/Seun, Oluwafemi/Femi | ~12 |
| Igbo | Chukwuemeka/Emeka, Nkechi/Nkechinyere | ~10 |
| Akan/Twi | Kwame/Kwamena, Kofi/Koffi | ~10 |
| Hausa | Muhammadu/Mamman, Abdullahi/Abdulahi | ~8 |
| Colonial-era | Pierre/Peter, Jean/John, Marie/Mary | ~12 |
| Swahili | Juma/Jumah, Amani/Imani | ~8 |
| Cross-border | Same name, different countries' spellings | ~9 |

These groups were compiled from civil registration records, census data, and linguistic research across 20+ African countries.

---

## Use in a resolution pipeline

The naming intelligence is built into `link()` automatically -- when you resolve entities across two sources, equivalent name variants collapse into one identity:

```python
from arche import detect, link

source_a = detect("Fatima Abdullahi from the Lagos CRVS registry.")
source_b = detect("Fatoumata Abdoulaye from the MOSIP enrollment center.")

graph = link(source_a, source_b, jurisdiction="NG")

for identity in graph.resolved:
    if identity.sources > 1:        # linked across both sources
        print(identity.canonical_name)
        print(f"  Aliases: {', '.join(identity.aliases)}")
        print(f"  Confidence: {identity.confidence:.0%}")
```

```
Fatoumata Abdoulaye
  Aliases: Fatima Abdullahi
  Confidence: 100%
```

You do not need to call `are_names_equivalent()` directly -- it is used automatically during the link/resolution step.

---

## Add new equivalences

The equivalence data lives in `datasets/name_equivalences/` as YAML files. To add a new equivalence group:

1. Find or create the appropriate YAML file (e.g., `yoruba.yaml`, `hausa.yaml`)
2. Add a new group entry with all known variants
3. Run the test suite to verify: `uv run pytest tests/ -k "naming"`

Example YAML entry:

```yaml
- group: "fatima_variants"
  names:
    - Fatima
    - Fatoumata
    - Fatimata
    - Fatimah
    - Fati
    - Fatouma
  tradition: "pan_islamic"
  notes: "Arabic origin, variants across West Africa"
```

Contributions to the naming dataset are welcome. See the [Contributing guide](https://github.com/unpatterned-labs/archetree/main/datasets) for details.

---

## What's next

- [Architecture](../concepts/architecture.md) -- how resolution uses cultural naming
- [API: resolve()](../api/resolve.md) -- full function documentation
- [Quick Start](../getting-started/quickstart.md) -- more examples
