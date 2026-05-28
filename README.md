# arche-core

**African PII detection that cites the law it enforces.**

`arche-core` detects PII for African jurisdictions; government IDs, names, phone numbers, addresses, and grounds every detection in the data protection statute that governs it. NDPA, POPIA, Kenya DPA, Ghana DPA. Six closed policy actions. Composes with Presidio, GLiNER, and Splink.

> Presidio detects PII. GLiNER does multilingual NER. Splink links records. None of them know that a BVN is sensitive under NDPA §30, or that "Adeyẹmí" and "Adeyemi" are the same Yoruba name with and without tonal marks, or that "behind Total filling station, Madina Junction" is a parseable Ghanaian address. `arche-core` does that one job.

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

Same code works for `jurisdiction="ZA"` (POPIA), `"KE"` (Kenya DPA), `"GH"` (Ghana DPA). Four launch jurisdictions, four DPA-grounded statute YAML files, one composable framework.

## Install

```bash
pip install arche-core          # ~310KB base — pure-Python detectors, statute policy
pip install arche-core[all]     # everything (GLiNER + Presidio + Splink + docling + LLM)
```

(Or `uv add arche-core` / `uv add arche-core[all]`.) Heavy capabilities are **opt-in extras**:

| Extra | Adds |
|---|---|
| `arche-core[detect]` | GLiNER2-PII via ONNX runtime (multilingual neural soft-PII) |
| `arche-core[presidio]` | Microsoft Presidio recognizer plugin |
| `arche-core[resolve]` | Splink + DuckDB for large-scale entity resolution |
| `arche-core[doc]` | docling for PDF / DOCX / PPTX / XLSX ingestion |

## Coverage

Per-launch-jurisdiction detection coverage. Every detector validates check-digits where the underlying spec supports it.

| Jurisdiction | Statute | Detectors |
|---|---|---|
| Nigeria (NG) | NDPA-2023 | NIN (11 digits), BVN (11 digits, 22-prefix), TIN, RC, voter PVC, driver's licence |
| Kenya (KE) | Kenya DPA 2019 | National ID, KRA PIN, NHIF |
| South Africa (ZA) | POPIA | SA ID (13-digit Luhn + DOB/gender/citizenship decode), tax reference, passport |
| Ghana (GH) | Ghana DPA 2012 | Ghana Card, SSNIT, TIN |
| + 11 more African patterns | — | Egypt, Uganda, Rwanda, Tanzania, Cameroon, Senegal, ... |

Plus libphonenumber-backed normalization for 30+ African phone networks, landmark-anchored address parsing for NG and ZA, and currency detection (Naira, Cedi, Rand, CFA).

## The statute layer

Every detection emits a category, a sensitivity tier (`high` / `moderate` / `low`), and the specific statute section that classifies it. The Pipeline maps each to one of six closed actions — `mask`, `tokenize`, `drop`, `generalize`, `audit`, `retain` — per the configured jurisdiction's statute YAML.

```python
for o in result.policy_outcomes:
    print(o.category, o.action, o.statute_reference)
# PII-2-BVN    mask       NDPA-2023 s.30, CBN BVN policy 2014
# PII-2-NIN    mask       NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME   tokenize   NDPA-2023 s.30
```

Statute YAMLs live at `arche/policy/_data/<STATUTE-ID>.yaml` and are human-readable. Statute amendments are policy-file changes, not code changes.

## Cultural naming intelligence

`arche-core` ships a 114-group African name equivalence lexicon covering 454 name forms across 50+ ethnic traditions:

- Mohammed = Muhammad = Mamadou = Muhammadu (Pan-Islamic)
- Diallo = Jallow = Jalloh (Fulani cross-ethnic orthography)
- Fatou = Fatoumata (West African diminutive)
- Adeyemi = Adeyẹmi = Adeyẹmí (Yoruba tonal marks)
- Pierre = Peter = Pedro (colonial-era cross-linguistic)
- Irorere, Aibuedfe (Benin/Edo names with semantic meaning)

Growing via Wikidata + community curation. See [`datasets/`](../../datasets/) for the full dataset and contribution guide.

## Composing with Presidio, GLiNER, and Splink

`arche-core` is designed to compose with the incumbent tools, not replace them. The three integration patterns:

```python
# Presidio's English recognizers + arche's African recognizers
pip install arche-core[presidio]
# arche.detect.presidio surfaces both as one recognizer set.

# GLiNER's multilingual NER + arche's statute classification
pip install arche-core[detect]
# Pipeline(jurisdiction="NG", backend="gliner") routes soft-PII through GLiNER.

# Splink's record linkage + arche's jurisdiction-aware comparators
pip install arche-core[resolve]
# Statute-tagged detections feed Splink as clean inputs.
```

## Audit log

`arche.graph.audit` ships an SQLite-backed append-only log that records every detection, every policy decision, and every action taken — queryable by compliance officers and regulators. **PII values are never stored**; only categories, span offsets, and document hashes. Markdown compliance report generator for regulator-ready exports.

## Power-user features

These ship in the package but are not in the headline pitch — they support specific identity workflows on top of the detection layer:

- **`arche.sign`** — Ed25519 + JWS + did:key signing for `Pipeline.Result` envelopes. SD-JWT-VC issue / verify via `arche.credentials.sd_jwt`. See [`examples/02_sign_share_extract.py`](../../examples/02_sign_share_extract.py) and [`examples/04_sd_jwt_credential.py`](../../examples/04_sd_jwt_credential.py).
- **`arche.workflow.dsar`** — citizen-side DSAR draft generation with per-jurisdiction statute citations. See [`examples/03_dsar_workflow.py`](../../examples/03_dsar_workflow.py).
- **`arche.resolve`** — lightweight Fellegi-Sunter matcher with jurisdiction-specific priors. `from arche import match` for two-record comparison; `from arche import link` for cross-source resolution.
- **`arche.workflow._review`** — MPI review queue for human-in-the-loop match decisions. Not on the public surface; import from the canonical path.
- **`arche.resolve_places` / `arche.list_places`** — jurisdictional place lookup with verifiable audit receipts.

These are real tools we depend on internally. They are not the lead pitch.

## Migrating from v0.1

`resolve()` and the v0.1 helpers (`extract`, `resolve_entities`,
`detect_pii`, `to_html`, etc.) remain importable via PEP 562 lazy attribute access, with a `DeprecationWarning` on first use. Migrate to
`Pipeline.process()` for statute-aware policy and regulatory citations. The v0.1 surface is removed in v0.3. See the
[CHANGELOG](./CHANGELOG.md) for per-release migration notes.

## License

Apache 2.0. By [Unpatterned Labs](https://unpatterned.org).
