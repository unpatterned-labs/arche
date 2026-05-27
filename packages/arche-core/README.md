# arche-core

**PII + digital identity detection with statute-aware policy.** *African-first, globally pluggable.*

Detect PII, government IDs, phones, addresses, and IPs across African jurisdictions. Every detection carries the **regulatory citation** it was made under and a **sensitivity tier** (high / moderate / low). Apply six closed policy actions — mask, tokenize, drop, generalize, audit, retain — grounded in NDPA-2023, POPIA, Kenya DPA, or Ghana DPA.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")        # auto-loads NDPA-2023
result = pipeline.process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)

for d in result.detections:
    print(f"{d.category:11} tier={d.sensitivity_tier.value:9} {d.regulatory_citation}")
# PII-2-BVN   tier=high      NDPA-2023 s.30, CBN BVN policy 2014
# PII-2-NIN   tier=high      NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME  tier=moderate  NDPA-2023 s.30            (×2 — given + family name)

print(result.redacted_text)
# NAME_... NAME_..., NIN [NIN], BVN [BVN].
```

Same code works for `jurisdiction="ZA"` (POPIA), `"KE"` (Kenya DPA), `"GH"` (Ghana DPA) — four launch jurisdictions, four DPA-grounded statute YAML files, one composable framework.

## Install

```bash
pip install arche-core          # base — pure-Python detectors, statute policy, signing
pip install arche-core[all]     # everything (GLiNER + Splink + Presidio + docling + LLM)
```

(Or `uv add arche-core` / `uv add arche-core[all]`.) Heavy capabilities are **opt-in extras** so the base install stays lean — no mandatory ML dependencies:

| Extra | Adds |
|---|---|
| `arche-core[detect]` | GLiNER2-PII via ONNX runtime (multilingual neural soft-PII) |
| `arche-core[presidio]` | Microsoft Presidio recognizer plugin |
| `arche-core[resolve]` | Splink + DuckDB for large-scale entity resolution |
| `arche-core[pdf]` / `[docx]` | file-to-text ingestion |

## The Pipeline primitive

`Pipeline(jurisdiction=...).process(text)` composes detection + statute policy + audit in one call and returns a `Result`.

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)

# Every detection: category, sensitivity tier, and the statute section behind it
for d in result.detections:
    print(d.category, d.sensitivity_tier.value, d.regulatory_citation)

# What the policy engine decided, and its statute reference
for o in result.policy_outcomes:
    print(o.category, o.action, o.statute_reference)
# PII-2-BVN    mask       NDPA-2023 s.30, CBN BVN policy 2014
# PII-2-NIN    mask       NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME   tokenize   NDPA-2023 s.30

print(result.redacted_text)   # ready to log or share
```

`Result` exposes `detections`, `policy_outcomes`, `redacted_text`, `audit_log`, `document_hash`, and `metadata`. Each outcome cites the **actual statute section** — defensible in an audit, not a heuristic guess.


## Composable building blocks: detect / match / link

When you don't need full policy enforcement, the workhorse functions give you each stage on its own.

```python
from arche import detect, match, link

# Detect — extract identity entities from text
entities = detect("Invoice from Acme SARL, 14 Rue de Rivoli, Paris. Contact: J. Dupont")

# Match — compare two entities or records
score = match("Mamadou Diallo", "Mohamed Diallo")           # → 0.989 (cultural equiv)
score = match("J. Dupont", "Jean Dupont")                   # → 0.974 (initials)
score = match("+234 801 234 5678", "08012345678",
              entity_type="phone")                           # → 0.999 (normalised)

# Match with full Fellegi-Sunter record comparison
score = match(
    {"name": "Fatima Abdullahi", "phone": "+234 803 555 7890", "national_id": "12345678901"},
    {"name": "F. Abdullahi", "national_id": "12345678901"},
    jurisdiction="NG",
)
print(score)          # MatchScore(score=1.0, decision='match')
print(score.factors)  # {'name': 0.80, 'national_id': 1.0}

# Link — resolve entities across multiple sources
entities_a = detect(text_from_health_system)
entities_b = detect(text_from_civil_registry)
graph = link(entities_a, entities_b, jurisdiction="NG")

for identity in graph.resolved:
    if identity.sources > 1:
        print(f"LINKED: {identity.canonical_name} ({identity.sources} sources)")
        print(f"  Aliases: {identity.aliases}")
```

## Entity Relationships

arche doesn't just extract entities — it understands **who owns what**. Given entities in text, `group_by_identity()` clusters them by proximity and context, linking persons to their phones, IDs, and addresses.

```python
from arche import detect, group_by_identity

text = (
    "Fatima Abdullahi, NIN 12345678901, phone +234 803 555 7890, Lagos. "
    "Kwame Mensah from Accra, Ghana Card GHA-123456789-0."
)

entities = detect(text)  # with GliNER: extracts persons + IDs + phones + locations
clusters = group_by_identity(entities, text)

for cluster in clusters:
    if cluster.anchor:
        print(f"{cluster.anchor.text}:")
        for rel in cluster.relationships:
            print(f"  {rel.relation}: {rel.target.text}")

# Output:
# Fatima Abdullahi:
#   HAS_ID: 12345678901
#   HAS_PHONE: +234 803 555 7890
#   LOCATED_AT: Lagos
# Kwame Mensah:
#   LOCATED_AT: Accra
#   HAS_ID: GHA-123456789-0
```

Relationship types: `HAS_ID`, `HAS_PHONE`, `HAS_EMAIL`, `LOCATED_AT`, `AUTHORED`, `HAS_AMOUNT`, `ASSOCIATED_WITH`.

## ISBN Detection

arche detects ISBNs (ISBN-10 and ISBN-13) with checksum validation and uses them as identity anchors in record matching.

```python
from arche import detect, match

# Detect ISBNs in text (with checksum validation — rejects invalid ISBNs)
entities = detect(
    "Order: ISBN 978-0-13-468599-1 'Clean Code' by Robert Martin. "
    "Also ISBN 0-321-12521-5 'Domain-Driven Design'."
)
# → [ISBN("978-0-13-468599-1", type=ISBN-13), ISBN("0-321-12521-5", type=ISBN-10)]

# Match ISBNs across formats (ISBN-10 ↔ ISBN-13 of the same book)
score = match("0-321-12521-5", "978-0-321-12521-7", entity_type="isbn")
# → MatchScore(0.999, decision='match')

# Use ISBN as an identity anchor in record matching
score = match(
    {"name": "Robert C. Martin", "isbn": "978-0-13-468599-1"},
    {"name": "R. Martin", "isbn": "9780134685991"},
)
# → MatchScore(1.0, decision='match') — ISBN match dominates
```

For book metadata lookup (title, authors, publisher), call Open Library directly via `httpx` or use the `arche-live` package — `arche.enrich` was removed in v0.2.0a2 to keep the core SDK detection-focused.

## Fellegi-Sunter Matcher

arche includes a lightweight probabilistic identity matcher based on the Fellegi-Sunter model with jurisdiction-specific priors.

```python
from arche import match

# Jurisdiction priors adjust match weights based on name frequency
# "Mohammed" is very common in Nigeria (u=0.08) but less so in France (u=0.03)
score_ng = match("Mohammed Ali", "Mohammed Ali", jurisdiction="NG")  # → 0.920
score_fr = match("Mohammed Ali", "Mohammed Ali", jurisdiction="FR")  # → 0.968

# Multi-field comparison produces Fellegi-Sunter log-odds
score = match(
    {"name": "Oluwaseun Adeyemi", "phone": "+2348012345678"},
    {"name": "O.S. Adeyemi", "phone": "08012345678"},
    jurisdiction="NG",
)
# score.factors → {'name': 0.88, 'phone': 1.0}
# score.explanation → "name similarity 88%; phone match"
```

Supported fields: `name`, `phone`, `national_id`, `email`, `address`, `dob`.

Built-in priors for: Nigeria (NG), Ghana (GH), Kenya (KE), South Africa (ZA), France (FR). Falls back to sensible defaults for other jurisdictions.

## Five Entity Types

arche detects, matches, and links five identity entity types:

| Entity Type | Examples | Detection |
|---|---|---|
| **Person** | "Fatima Abdullahi", "J. Dupont" | GliNER + regex |
| **Business** | "Acme SARL", "MTN Nigeria Plc" | GliNER |
| **ID Number** | NIN, BVN, Ghana Card, SIREN, SA ID | Regex + checksum validators |
| **Address** | "14 Rue de Rivoli", "behind Tantalizers, Allen Ave" | GliNER + regex |
| **Financial** | IBAN, account numbers | Regex + Luhn validation |

Plus: Phone numbers (30+ African networks), emails, dates, currencies (Naira, Cedi, Rand, CFA).

## Cultural Naming Intelligence

arche handles what no other ER tool can:

- **114+ equivalence groups** covering 454 name forms across 50+ ethnic traditions
- Mohammed = Muhammad = Mamadou = Muhammadu (Pan-Islamic)
- Diallo = Jallow = Jalloh (Fulani cross-ethnic)
- Fatou = Fatoumata (West African diminutive)
- Adeyemi = Adeyẹmi = Adeyẹmí (Yoruba tonal marks)
- Pierre = Peter = Pedro (colonial-era cross-linguistic)
- Irorere, Aibuedfe (Benin/Edo names with semantic meaning)

Growing via Wikidata + community curation. See [datasets/](../../datasets/) for the full dataset and contribution guide.

## PII Protection

Presidio + 50 African ID format validators:

| Country | ID Types |
|---|---|
| Nigeria | NIN (11 digits), BVN (11 digits, 22-prefix), PVC, TIN, NHIS, NHF |
| Ghana | Ghana Card |
| Kenya | National ID |
| South Africa | 13-digit ID (Luhn-validated, embeds DOB + gender) |
| + 11 more | Egypt, Uganda, Rwanda, Tanzania, Cameroon, Senegal, ... |

Jurisdiction-aware classification: knows that a BVN is "sensitive" under Nigeria's NDPA, while a phone number is "personal" under South Africa's POPIA. Run through the `Pipeline` and that classification surfaces as each detection's `sensitivity_tier` + `regulatory_citation`.

## Output Formats & Visualization

The v0.2 `Pipeline` `Result` is a plain dataclass — read `result.redacted_text`, `result.detections`, and `result.policy_outcomes` directly, or `dataclasses.asdict(result)` to serialize.

The legacy `resolve()` result ships richer export + visualization helpers:

```python
from arche import resolve
result = resolve(text)
result.to_dict()              # Python dict
result.to_json()              # JSON string
result.export("out.json")     # JSON file
result.export("out.csv")      # CSV file
result.sanitize_for_logging() # PII-safe dict

# Visualization (operate on the resolve() result)
from arche import to_html, to_graph_html, to_csv, to_dot
to_html(result)               # Standalone HTML report
to_graph_html(result)         # Interactive vis.js graph
to_csv(result)                # CSV export
to_dot(result)                # Graphviz DOT
```

## Legacy v0.1 API

The single-call `resolve()` plus the raw stage functions remain available for v0.1 users. Calling `resolve()` emits a `DeprecationWarning`; migrate to `Pipeline.process()` for statute-aware policy, citations, and sensitivity tiers.

```python
from arche import resolve

result = resolve("Fatima Abdullahi, NIN 12345678901, +234 803 555 7890")
print(result.entities)    # Extracted entities with confidence scores
print(result.resolved)    # Resolved identities (Fatima = Fatoumata = Fatimah)
print(result.pii)         # PII detections (NIN, phone numbers)

# Raw stage functions
from arche import extract, resolve_entities, detect_pii
entities = extract(text, backend="gliner")
resolved = resolve_entities(entities)
pii = detect_pii(text)
```


## License

Apache 2.0 — free forever.
