# Introducing arche v0.2 — African PII detection that cites the law it enforces

*One PyPI package. Four DPA-grounded statutes. 310KB wheel. By Unpatterned Labs.*

---

!!! warning "Status: pre-beta (development) — not for production use yet"
    `arche-core` v0.2.0a3 is on PyPI for research, prototyping, evaluation, and contribution. APIs may change between alpha releases. Production use against real personal data is not recommended until v0.3 (beta).

Six months ago we said arche was an *"identity workflow framework"* — a five-step Detect → Resolve → Link → Verify → Govern pipeline that would compose with everything African DPI needed. Six months in, the lesson is sharp: that pitch is too broad, hard to remember, and harder to deliver. **arche v0.2 narrows.**

> arche-core does one job: **detect PII in African text and ground every detection in the data protection statute that classifies it.**

Nigerian NIN, BVN, TIN, RC, voter PVC, driver's licence. Kenyan National ID, Huduma, KRA PIN, NHIF. South African ID with Luhn validation and DOB / gender / citizenship decode. Ghana Card, SSNIT, TIN. libphonenumber-backed normalization for 30+ African networks. A 114-group African name equivalence lexicon. NG and ZA address parsing. Plus: every detection emits a sensitivity tier (`high` / `moderate` / `low`) and the specific statute section that classifies it (e.g. `NDPA-2023 s.30, NIMC Act s.27`), mapped to one of six closed actions: `mask`, `tokenize`, `drop`, `generalize`, `audit`, `retain`. That's the whole pitch.

## Three lines

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012."
)
print(result.redacted_text)
# "Customer NAME_..., NIN [NIN], BVN [BVN]."
```

Same code, different jurisdictions:

```python
Pipeline(jurisdiction="ZA")   # auto-loads POPIA
Pipeline(jurisdiction="KE")   # auto-loads Kenya DPA
Pipeline(jurisdiction="GH")   # auto-loads Ghana DPA
```

Four jurisdictions. Four DPA-grounded statute YAML files. One composable framework.

## Why not just use Presidio? Or GLiNER? Or Splink?

We aren't replacing them. We're composing with them.

Presidio detects PII for English-centric corpora and handles structured anonymization. GLiNER does multilingual NER as binary classification. Splink does probabilistic record linkage at scale. None of them know that *Adeyẹmí* and *Adeyemi* are the same Yoruba name with and without tonal marks, that *Mohammed* / *Muhammad* / *Mamadou* are Pan-Islamic equivalents, that a BVN is sensitive under NDPA §30, or that *"behind Total filling station, Madina Junction"* is a parseable Ghanaian address.

```bash
pip install arche-core[presidio]     # Presidio's recognizers + arche's African layer
pip install arche-core[detect]       # GLiNER multilingual NER + arche's statute classification
pip install arche-core[resolve]      # Splink at scale, fed by arche's statute-tagged detections
```

The base install is a ~310KB wheel with no mandatory ML dependencies. Heavy capabilities are opt-in extras.

## The moat is the combination

Pure statute grounding is not a moat. If Microsoft ships *"Presidio African Language Pack"* in eighteen months, regex detectors are commodity. The defensible asset is the combination of the **African-context layer** (government ID rules with check digits; phone normalization; 114 name equivalence groups; landmark-anchored address parsing; currency detection) with the **statute-aware layer** (versioned statute YAML per jurisdiction; six closed actions; sensitivity tiers; regulatory citations; auditable, replayable decisions). Either half alone is replicable; together — maintained, versioned, tested, DPA-consulted, citation-backed — that's the work.

Presidio is a detection library. arche-core aims to be a detection library that produces **auditable compliance evidence** — one that a Nigerian fintech's compliance officer can point an auditor at and say *"here is the rule, here is the citation, here is the audit log."*

## What's actually shipped in v0.2.0a3

- **Per-country detectors** for NG, KE, ZA, GH with check-digit / structural validation. Plus 11 additional African country patterns.
- **libphonenumber-backed phone normalization** for 30+ African networks.
- **114-group name equivalence lexicon** (454 forms, 50+ ethnic traditions).
- **Address parser MVP** for Nigeria and South Africa with landmark-anchored format support.
- **Statute YAML files**: NDPA-2023 (full v1.0); POPIA, Kenya DPA, Ghana DPA (v0.1 scaffolds awaiting DPA consultation).
- **`Pipeline` framework primitive** composing detection + policy + audit in one call.
- **SQLite audit log**: append-only, PII values never stored, markdown compliance reports, JWS-signed regulator exports.
- **Pan-African PII Taxonomy v0.1** — 51 categories with the four-class identity-class distinction. CC-BY-4.0.
- **Optional integrations** as opt-in extras: GLiNER2-PII, Microsoft Presidio, Splink + DuckDB, docling.

980 tests passing, 3 skipped, 0 failed. Wheel size: 308KB. Python 3.11 / 3.12 / 3.13 supported. License: Apache 2.0.

## What's also shipped, but not in the headline

These features ship in the package today and are documented as power-user workflows. They are not in the lead pitch because the lead pitch is one job:

- **`arche.sign`** — Ed25519 + JWS + did:key signing for `Pipeline.Result` envelopes. Verifiability that works offline.
- **`arche.credentials.sd_jwt`** — SD-JWT-VC issue / verify with holder-controlled selective disclosure.
- **`arche.workflow.dsar`** — citizen-side DSAR draft generation with per-jurisdiction statute citations.
- **`arche.resolve_places` / `arche.list_places`** — jurisdictional place lookup with verifiable receipts.
- **`arche.match` / `arche.link`** — lightweight Fellegi-Sunter matcher with jurisdiction-specific priors.

If you need any of them, they're there. If you don't, ignore them and use `Pipeline` directly.

## What's not in this release

For honesty's sake:

- **No fine-tuned PII model.** Detectors are rule-based + check-digit-validated. Soft-PII goes through GLiNER via the opt-in `[detect]` extra.
- **No production DPI adapters.** The v0.2.0a2 release deleted every MOSIP / OpenCRVS / DHIS2 / OpenG2P stub — they were scaffolding for work nobody had started. DPI integration ships when there's a real partner deployment in flight.
- **No MCP server.** Agent-integration surface is downstream of framework adoption.
- **POPIA / Kenya DPA / Ghana DPA at v1.0.** Those statute YAMLs are v0.1 scaffolds today; v1.0 ships after structured DPA consultation in the grant period.
- **Address parsing for Kenya or Ghana.** Nigeria and South Africa ship with the MVP parser. KE and GH are next quarter.

## The road to beta (v0.3)

Beta ships when:

- POPIA, Kenya DPA, and Ghana DPA statute YAMLs reach v1.0 after structured DPA consultation.
- The Africa Address Benchmark v0.1 is published with cross-tool baselines (libpostal + Google Geocoding).
- The v0.1 backward-compat shim is removed.
- At least one production deployment has been running cleanly for 90 days.

Until then: research, prototyping, evaluation, benchmarking, contributing. Bug reports very welcome.

## Where we go after that

The Stage 1 commitment is depth — finishing the four launch jurisdictions and proving the statute-grounded detection thesis works in production. After that, two expansion paths exist on the roadmap. We do not commit to either today; we name them so adopters can shape which one matters most to their use case.

- **Depth across the Global South.** Extending statute coverage and detector packs to additional African jurisdictions, then to other Global South jurisdictions where the same statute-grounded detection thesis applies: India's DPDP Act, Brazil's LGPD, Indonesia's PDP Act, the Philippines' DPA. Each new jurisdiction is a YAML statute file and a per-country detector pack, layered on the same core.

- **Sector-aligned packs.** Layering domain-specific detectors and statute extensions over the African base. Health (POPIA Section 32 special-category data; NDPA s.30 health records; HIPAA crosswalks for African health-data-export workflows). Energy (utility account identifiers; SIM-registered meter readings; payment-rail identifiers). Manufacturing (worker ID schemes; supply-chain traceability). Agriculture (smallholder farmer registries; mobile-money disbursement flows; cooperative membership IDs).

These are roadmap, not v0.3. The honest sequencing: get NG / KE / ZA / GH to production quality first, ship the Africa Address Benchmark, complete the four DPA consultations, document one named sectoral pilot. Then expand.

## Get started

```bash
pip install arche-core
```

```python
from arche import Pipeline
result = Pipeline(jurisdiction="NG").process("Your text here...")
print(result.redacted_text)
```

- **GitHub**: [github.com/unpatterned-labs/arche](https://github.com/unpatterned-labs/arche)
- **PyPI**: [pypi.org/project/arche-core](https://pypi.org/project/arche-core/)
- **Quick Start**: [docs.unpatterned.org → Quick Start](../getting-started/quickstart.md)
- **Why arche & when to use it**: [persona guide + cross-tool benchmark](../tutorials/arche_vs_alternatives.md)

License: Apache 2.0.

---

*arche is built by [Unpatterned Labs](https://unpatterned.org), a non-profit researching open infrastructure for how the world is represented in data, identity, and intelligence. The name comes from the Greek ἀρχή — origin, first principle, foundation. Finding the foundational truth of who someone is.*
