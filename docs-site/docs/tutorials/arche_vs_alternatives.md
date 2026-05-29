# Why arche, and when to use it

A practical guide for developers, researchers, DPOs, and civil society choosing between `arche-core` and the other tools in the PII landscape. Honest about what arche is, what it isn't, and where the alternatives are the better pick.

!!! warning "Status: pre-beta (development) — not for production use yet"
    See the [roadmap](../concepts/roadmap.md) for the named beta criteria. Suitable today for research, prototyping, evaluation, benchmarking, and contributing.

---

## The setup

You're building something that handles African data — a Nigerian fintech onboarding flow, a Kenyan health-tech intake screen, a journalist's PII scanner for leaked emails, a South African civil-society audit of a public dataset. You need to detect PII. You install [Microsoft Presidio](https://microsoft.github.io/presidio/) (the obvious choice). You feed it a sample customer record:

```
Customer Fatima Abdullahi, NIN 12345678901, BVN 22156789012, phone 0803 555 7890, RC 245678.
```

Presidio confidently returns:

```
NIN 12345678901  → US_BANK_NUMBER  ✗
BVN 22156789012  → US_BANK_NUMBER  ✗
0803 555 7890   → US_PHONE_NUMBER  ✗ (it's a Nigerian network)
RC 245678        → (not detected)  ✗
```

That's not a typo. Presidio's default recognizers literally label Nigerian customers as having US bank accounts. Same story for Ghana Card (gets called `US_PASSPORT`), South African ID, Kenyan KRA PIN. The Presidio team isn't wrong — they built recognizers for the data their users had. Your data isn't their data.

**Same input, `arche-core`:**

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Customer Fatima Abdullahi, NIN 12345678901, BVN 22156789012, "
    "phone 0803 555 7890, RC 245678."
)
```

```
PII-1-NAME      "Fatima Abdullahi"  tier=moderate  NDPA-2023 s.30
PII-2-NIN       "12345678901"       tier=high      NDPA-2023 s.30, NIMC Act s.27
PII-2-BVN       "22156789012"       tier=high      NDPA-2023 s.30, CBN BVN policy 2014
PII-3-PHONE     "0803 555 7890"     tier=moderate  NDPA-2023 s.26
PII-2-RC        "245678"            tier=low       NDPA-2023 s.31 (legitimate interests)
```

Every detection: validated checksum, the statute section that classifies it, the sensitivity tier, the policy action that follows. Change `jurisdiction="NG"` to `"ZA"` and you get POPIA. `"KE"` for Kenya DPA. `"GH"` for Ghana DPA. Same code; four jurisdictions.

That's the gap in one example. The rest of this page is the proof, the personas, and the honest limitations.

---

## The proof — cross-tool benchmark

From [`benchmarks/lingua-africa-eval-v0.2`](https://github.com/unpatterned-labs/arche/blob/main/benchmarks/lingua-africa-eval-v0.2.md): **48 synthetic test cases across six anchor languages** (English, Nigerian Pidgin, Yoruba, Hausa, Swahili, Amharic) covering NG / KE / ZA / GH government identifiers, IPs, DIDs, and crypto wallets. CC-BY-4.0. Reproducible from `pip install arche-core[presidio]` plus one script.

| Tool | Cases matching expected categories | Notes |
|---|---|---|
| **arche-core v0.2.0a3** | **47 / 48** | All African IDs detected across all six anchor languages. Luhn validators correctly reject negative-control invalid SA ID. Cross-cutting detectors (IP, DID, crypto wallet) work irrespective of surrounding script. The one gap is PVC (NG voter card) detection — documented post-beta work. |
| **Microsoft Presidio** (default, generous "any non-empty" scoring) | **37 / 48** | On generous scoring, passes negative tests and IP / crypto cases. On per-category matching the picture inverts: Presidio scores **2 / 25** on cases where the expected label is a specific PII-2 / PII-5 / PII-8 category — and confidently mislabels NG NIN / BVN, SA ID, and Ghana Card as US-default types. Even Amharic text with an embedded NG NIN gets labeled `US_BANK_NUMBER`. |
| **GLiNER2-PII** (Fastino) | Not run standalone | Install pulls ~2.5 GB of torch + transformers. Public schema covers 42 PII categories — **none are African government IDs**. Composed via `arche-core[detect]` extra for soft-PII coverage. |
| **OpenAI Privacy Filter** | Not run | API-only. No published per-category breakdown. Closed-weight model — auditability question open. |

The headline: **Presidio's default recognizers actively harm African DPI compliance work** by labelling Nigerian customers as having US bank accounts. arche-core ships the African recognizers that close this gap — and the regexes that drive them are script-agnostic for ASCII identifier shapes, so Yoruba / Hausa / Amharic narratives wrapped around an NIN or KRA PIN still detect correctly.

Per-language breakdown (arche, 48 total cases):

| Language | Cases | arche |
|---|---|---|
| English | 8 | 8 / 8 |
| Nigerian Pidgin | 8 | 8 / 8 |
| Yoruba | 8 | 8 / 8 |
| Hausa | 8 | 7 / 8 *(PVC post-beta)* |
| Swahili | 8 | 8 / 8 |
| Amharic | 8 | 8 / 8 |

A v0.1 baseline (15 cases, English-only) is preserved as [`lingua-africa-eval-v0.1`](https://github.com/unpatterned-labs/arche/blob/main/benchmarks/lingua-africa-eval-v0.1.md) for historical comparison. The grant-period expansion is **1000+ examples per language across six anchor languages** with arche-core, arche-core + GLiNER2-PII, Presidio + custom African recognizers (we contribute upstream), GLiNER2-PII alone, and OpenAI Privacy Filter via API.

---

## Try it before you read the rest

The fastest way to internalise the difference is to paste your own text into the [live demo](https://demo.unpatterned.org). Pick a jurisdiction, paste any text (synthetic only — never real PII), see the detection set with tier and citation, see the policy decisions, see the PII-free audit log, walk away with a JWS receipt that verifies offline. Four preloaded samples cover NG / ZA / KE / GH so you can see the surface in 30 seconds.

The demo runs on Streamlit Cloud and proxies the same `pip install arche-core` you'd install locally. No telemetry, no PII storage. Source: [`demo/app.py`](https://github.com/unpatterned-labs/arche/blob/main/demo/app.py).

---

## What arche actually does that nothing else does

Three concrete gaps no other tool in the PII landscape closes:

### 1. Per-country African identifier coverage with check-digit validation

The Pan-African PII Taxonomy v0.1 covers 51 categories across NDPA-2023 (Nigeria), POPIA (South Africa), Kenya DPA, and Ghana DPA. The shipped detectors include **NIN, BVN, RC, TIN, voter PVC, driver's licence (NG); national ID, KRA PIN, NHIF (KE); SA ID with full Luhn + structural decode, tax reference, passport (ZA); Ghana Card, SSNIT, TIN (GH)** — plus 11 non-launch African country patterns (RW, TZ, UG, ET, CI, SN, CM, EG, MA, AO, MZ). Every detector validates check-digits where the underlying spec supports it; structural validators drop false positives at detection time, before policy applies.

Presidio's default recognizers ship **none** of these. You'd write each one yourself, maintain the regex against ID-scheme amendments, and integrate with your audit layer. Multiply by four jurisdictions and you have a quarter of an engineer's time wired to a problem that arche solves at `pip install` time.

### 2. Sensitivity tier and statute citation on every Detection

Detection is one floor. Every `Detection` arche emits carries `sensitivity_tier` (`HIGH` / `MODERATE` / `LOW` per the loaded statute) and `regulatory_citation` (the exact statute section) — populated from the statute YAML at detection time, before the policy engine fires. Tier-aware dashboards, per-citation compliance reports, and HIGH-tier routing become properties of the data structure, not a downstream join you have to build.

The statute YAMLs live in `arche/policy/statutes/`: **NDPA-2023.yaml** at v1.0 with §24 / §26 / §29 / §34-38 cited inline; **POPIA.yaml, KENYA-DPA.yaml, GHANA-DPA.yaml** at v0.1 scaffold pending DPA consultation. Statute amendments are YAML changes, not code changes — you can read them, audit them, fork them, version them in git.

```python
from arche.policy import load_statute

statute = load_statute("NDPA-2023")
print(statute.categories["PII-2-NIN"].citation)
# "NDPA-2023 s.30, NIMC Act s.27"
```

No other open-source PII library produces this — *here is the rule the redaction enforced* — as a property of every detection. Combined with the audit log below it gives you regulator-ready evidence at the SDK level.

### 3. Cultural naming intelligence — 114 equivalence groups

```python
from arche.detect._names.lexicon import are_names_equivalent

are_names_equivalent("Adeyẹmí", "Adeyemi")
# (True, 0.96) — Yoruba tonal mark equivalence

are_names_equivalent("Mamadou Diallo", "Mohamed Diallo")
# (True, 0.92) — Fulani / Arabic Pan-Islamic equivalence

are_names_equivalent("Chukwuemeka Okafor", "Emeka Okafor")
# (True, 0.95) — Igbo prefix-elision

are_names_equivalent("Fatima Abdullahi", "Fatoumata Abdoulaye")
# (True, 0.89) — Hausa / Wolof cognates
```

114 equivalence groups, 454 name variants, 50+ ethnic traditions. Tested against a Jaro-Winkler baseline:

| Metric | Jaro-Winkler | arche | Delta |
|---|---|---|---|
| F1 | 0.849 | **0.988** | **+16.3%** |
| Precision | 1.000 | 1.000 | 0.0% |
| Recall | 0.738 | 0.976 | +23.8% |

Zero false positives — the lexicon is conservative by design. arche never claims equivalence between *Mamadou* and *Mary*; only between genuinely co-referential variants documented by African linguists.

---

## What else ships in the package (power-user)

These features ship today and are fully tested, but they're not the lead pitch. Read the row that matches your use case; skip the rest.

| Feature | Module | One-line | When you'd use it |
|---|---|---|---|
| **Sign, share, extract** | `arche.sign`, `arche.credentials.sd_jwt` | Ed25519 + JWS signing of `Pipeline.Result`; SD-JWT-VC re-framing for wallet interop. Offline verification with `did:key`. | Compliance officer needs a regulator-ready signed audit bundle. DSAR response that crosses an organizational trust boundary. KYC attestation a wallet can carry. |
| **Citizen-side DSAR** | `arche.workflow.dsar` | Draft-only DSAR letter generation citing NDPA s.34 / POPIA s.23 / Kenya DPA s.26 / Ghana DPA s.35. Per-jurisdiction. | Civil-society org training citizens to exercise rights. Journalist filing a DSAR as part of an investigation. |
| **Entity resolution** | `arche.match`, `arche.link`, `arche.resolve` | Lightweight Fellegi-Sunter matcher with jurisdiction-specific priors. African-name-aware comparator functions. | Deduplicate up to ~100K records on a laptop. For billion-row scale, install `arche-core[resolve]` and feed Splink. |
| **Places resolution** | `arche.resolve_places`, `arche.list_places` | Jurisdictional place lookup with verifiable JWS audit receipts. UK first; African expansion is roadmap. | "Find me an NHS dentist near SW1" with a signed receipt for the query, the redaction, and the result. |
| **Append-only audit log** | `arche.graph.audit` | SQLite-backed log with markdown compliance reports and JWS-signed regulator exports. PII values never stored. | Standalone audit-log surface for an existing detection pipeline. NDPC quarterly handoff. |

---

## Why arche, by persona

### Developer building African fintech / healthtech / civic platforms

You're the primary persona. You're the one who installs `arche-core` first.

The shape of your problem: you have customer records with NIN / BVN / Ghana Card / SA ID. Your stack is FastAPI / Django / Streamlit. Your auditor will ask *"show me the rule that fired."* You don't want to write per-country regexes, maintain check-digit validators, hand-roll redaction logic, and build a statute-citation audit layer from scratch. You want `pip install` and three lines.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")            # auto-loads NDPA-2023
result = pipeline.process(customer_intake_text)
log_to_warehouse(result.redacted_text)            # safe to share
audit.emit_batch(result.audit_entries)            # PII-free audit row
```

You use arche when:

- Your customers carry **NIN, BVN, Ghana Card, SA ID, KRA PIN** and Presidio's defaults don't help.
- You need every detection to **cite the specific statute section** so when the regulator asks *"what rule fired?"* the answer is in your audit log, not your head.
- You ship records to downstream consumers and want each redacted output **cryptographically signed** so the consumer trusts it offline.
- You want **one `pip install`** instead of stitching Presidio + custom recognizers + signing + audit from scratch.

You probably do NOT use arche if your data is purely Western (US / EU) and you have no African footprint — Presidio + custom validators is more direct.

### Researcher in African NLP / responsible AI / PII benchmarking

```python
from arche import Pipeline

for sample in dataset:
    result = Pipeline(jurisdiction=sample.jurisdiction).process(sample.text)
    yield {
        "text": sample.text,
        "expected": sample.labels,
        "detected": [(d.category, d.span) for d in result.detections],
        "applied_policy": [(o.action, o.statute_section) for o in result.policy_outcomes],
    }
```

You use arche when:

- You're building a **Pan-African PII benchmark** and want versioned ground-truth labels grounded in the published taxonomy.
- You're benchmarking GLiNER2-PII / Presidio / OpenAI Privacy Filter against jurisdiction-aware ground truth and need a baseline that's *not* Western-default.
- You want to ship a citable **digital public good** alongside your paper — the [Pan-African PII Taxonomy v0.1 (CC-BY-4.0)](https://github.com/unpatterned-labs/arche/tree/main/datasets/pan-african-pii-taxonomy).

You probably do NOT use arche if your research target is state-of-the-art neural NER on English / EU corpora — `gliner-large-v2.5` or `dslim/bert-base-NER` is more direct.

### Compliance officer / DPO / regulator

```python
from arche.graph.audit import AuditLog
from arche.sign import generate_keypair

audit = AuditLog("./compliance.sqlite")
# Pipeline runs daily; every detection writes a PII-free row.

# Quarterly handoff to the regulator
officer_key = generate_keypair()
bundle = audit.export_signed(key=officer_key, purpose="ndpc_quarterly_audit")
# bundle is a JWS-signed regulator report. NDPC verifies offline.
```

You use arche when:

- The regulator wants an **append-only audit log** that proves PII was never stored — only category labels, character spans, document hashes.
- You need **JWS-signed export bundles** for periodic regulator handoff, verifiable offline by the regulator's tooling.
- Your organisation processes multi-jurisdictional data and needs a **single policy engine** that honours the right statute per record.
- You're preparing for an NDPC / Information Regulator / ODPC audit and need a regulator-ready compliance report on demand (`audit.compliance_report_markdown()`).

You probably do NOT use arche if your compliance regime is purely GDPR and your data has no African footprint — OneTrust / Privitar / commercial suites have richer GDPR-specific tooling.

### Journalist / civil society / data subject

```python
from arche.workflow import DSARWorkflow, DSARRequestor, DSAROrganization
from arche.sign import generate_keypair

citizen_key = generate_keypair()      # one-time, stored in your wallet
draft = DSARWorkflow(
    jurisdiction="NG",
    requestor=DSARRequestor(name="Adesola Okonkwo", identifier_label="NIN", ...),
    request_type="access",
    targets=[DSAROrganization(name="Sterling Bank", dpo_email="dpo@sterlingbank.ng")],
).run(citizen_key)

# draft.letter_text cites NDPA-2023 §34. draft.signed_envelope is JWS-signed.
# Email it. Two weeks later, the DPO is on the clock.
```

You use arche when:

- You're investigating how a Nigerian bank / health system / telco handles personal data and need to file a **statute-grounded DSAR**.
- You're a civil-society organisation training citizens to exercise data protection rights they have on paper but can't operationally use today.
- You're a journalist publishing a **PII audit** of public records, government data, court filings, or the official gazette — and need a reproducible detection set.

You probably do NOT use arche if you just want to scrub PII from a single document — a one-line regex is more direct.

---

## When to use each alternative

**Use Microsoft Presidio alone when:**

- Your data is English-language US / EU PII (SSN, credit card, IBAN, US phone, US address).
- You're already in the Microsoft ecosystem.
- You're willing to write per-country custom recognizers yourself.

**Use GLiNER2-PII (Fastino) alone when:**

- You want a single-model, GPU-friendly NER backbone.
- Your PII categories overlap with the 42 GLiNER2 ships.
- You can absorb the ~2.5 GB install footprint.

**Use Splink alone when:**

- You have 1M+ rows of clean structured data to dedupe.
- Your blocking and comparison logic is purely Western-name-based.
- You're comfortable with DuckDB, parameter estimation, and Fellegi-Sunter setup ceremony.

**Use OpenAI Privacy Filter alone when:**

- You're already calling OpenAI and want PII filtering as a side-effect.
- Closed-weight, non-auditable detection is acceptable.
- Your compliance regime doesn't require a per-decision audit trail.

**Use arche-core when:**

- Your data has any African footprint and you need detection that works out of the box.
- You need detection + policy + audit in one library, not three.
- You need offline verification of provenance.
- You need citizen-side rights tooling (DSAR).
- You want **one `pip install`** instead of stitching four tools and three custom recognizer sets.

**Use arche + Presidio (`arche-core[presidio]`) when:**

- Your data is mixed (African + Western), and you want Presidio's Western recognizers alongside arche's African recognizers under one unified taxonomy.

**Use arche + GLiNER2-PII (`arche-core[detect]`) when:**

- You need multilingual soft-PII coverage (free-form names, occupations) in code-mixed contexts like Nigerian Pidgin.
- The deterministic arche recognizers cover the hard structured IDs; GLiNER fills the soft entities.

**Use arche + Splink (`arche-core[resolve]`) when:**

- You have >100K records to dedupe and want African-name-aware blocking and comparators inside the Splink pipeline.

---

## Honest limitations of arche today (v0.2.0a3)

| Gap | Today | Where it goes |
|---|---|---|
| Full address parsing across all four launch jurisdictions | NG + ZA MVP today | Beta (v0.3): KE and GH coverage. Stage 2: full parser with GERS / Placekey emission. |
| Multilingual soft-PII | GLiNER2-PII via `[detect]` extra | Post-beta: optional fine-tuned model if demonstrated adoption justifies the training run. |
| PVC, GhanaPost GPS, M-Pesa references | Not detected | Per-detector beta-period work. |
| PQC signatures | Ed25519 only | `arche-core[pqc]` hybrid Ed25519 + ML-DSA (NIST FIPS 204) is roadmap, not committed. |
| W3C VC 1.1 JSON-LD emission | SD-JWT-VC only today | `arche-core[didkit]` extra is roadmap. |
| DSAR organisation-side workflow | Citizen-side only | Beta-period or later. |
| Hash-chained audit log | Schema ready, not populated | Beta-period work. |
| Statute YAMLs v1.0 | NDPA-2023 v1.0; others v0.1 scaffold | Beta criterion: all four DPA-consulted to v1.0. |
| MOSIP / OpenCRVS / DHIS2 / OpenG2P production adapters | **Not in scope** — adapter stubs were deleted in v0.2.0a2 | Ships when there's a real partner deployment in flight, not as scaffolding. |


---

## Install

```bash
pip install arche-core                     # Base — every persona above
pip install arche-core[detect]             # + GLiNER2-PII for multilingual soft-PII
pip install arche-core[presidio]           # + Presidio for Western PII overlap
pip install arche-core[resolve]            # + Splink + DuckDB for billion-row dedup
pip install arche-core[doc]                # + docling for PDF / DOCX / PPTX / XLSX
pip install arche-core[all]                # Everything above
```

```python
from arche import Pipeline
result = Pipeline(jurisdiction="NG").process("your text here")
```

---

## See also

- **[Cross-tool benchmark v0.2](https://github.com/unpatterned-labs/arche/blob/main/benchmarks/lingua-africa-eval-v0.2.md)** — reproducible 48-case comparison across six anchor languages.
- **[Case study A: NG invoice PDF, end to end](https://github.com/unpatterned-labs/arche/blob/main/notebooks/case-study-invoice.ipynb)** — docling-parsed invoice through Pipeline + sign + verify roundtrip.
- **[Case study B: BusinessDay article, the honest wedge boundary](https://github.com/unpatterned-labs/arche/blob/main/notebooks/case-study-web-article.ipynb)** — what arche does and doesn't surface on free-text journalism.
- **[Pan-African PII Taxonomy v0.1](https://github.com/unpatterned-labs/arche/tree/main/datasets/pan-african-pii-taxonomy)** — the ground truth the benchmark uses, published CC-BY-4.0.
- [Roadmap](../concepts/roadmap.md) — what's shipped today, what gates beta, where the project goes next.
- [How arche Works](../concepts/how-it-works.md) — the substrate-by-substrate walkthrough.
- [Power-user: Sign, share, extract tutorial](sign_share_extract.md)
- [Power-user: Citizen DSAR tutorial](citizen_dsar.md)
