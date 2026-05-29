# arche examples

Six copy-paste examples covering the arche-core v0.2 framework
primitives. Examples 01-05 run with the base install
(`pip install arche-core`) — no extras required. Example 06 requires
`arche-core[doc]`.

| # | File | What it shows |
|---|---|---|
| 01 | [`01_pipeline_ndpa.py`](01_pipeline_ndpa.py) | The `Pipeline` framework primitive — detection + jurisdiction-aware policy + audit in one call, with auto-loaded NDPA-2023. |
| 02 | [`02_sign_share_extract.py`](02_sign_share_extract.py) | The headline sign-share-extract chain. Issuer signs a document; recipient verifies offline and recovers the redacted text + policy outcomes. |
| 03 | [`03_dsar_workflow.py`](03_dsar_workflow.py) | Citizen-side DSAR workflow for NDPA / POPIA / Kenya DPA / Ghana DPA. Drafts compliant letters, signs each. |
| 04 | [`04_sd_jwt_credential.py`](04_sd_jwt_credential.py) | SD-JWT-VC selective disclosure (EUDI Wallet / MOSIP Inji format). Holder controls which claims to disclose to each verifier. |
| 05 | [`05_audit_log.py`](05_audit_log.py) | SQLite audit log per PRD §8.2 with markdown compliance reports and JWS-signed regulator export bundles. |
| 06 | [`06_doc_pipeline.py`](06_doc_pipeline.py) | docling-backed PDF/DOCX ingest → Pipeline → policy → signed export. Requires `pip install arche-core[doc]`. |

Run any of them:

```bash
python examples/01_pipeline_ndpa.py
python examples/02_sign_share_extract.py
# ...
```

## Concepts in two minutes

arche-core is **the identity workflow framework**. It organises identity
work into five lifecycle steps, each mapped to substrate modules:

1. **Detect** — `arche.detect.{ng,ke,za,gh,_africa}` + `arche.addr` find PII, identifiers, and addresses. Per-country detectors with check-digit validation, plus libphonenumber-backed phones.
2. **Resolve** — `arche.resolve` deduplicates identity mentions across documents (fuzzy + African-name equivalence; Splink via `[resolve]` for scale).
3. **Link** — Stage 2 grant work. DPI-system adapters (OpenCRVS, MOSIP, DHIS2, OpenG2P, FHIR) need real integration testing against running systems and ship under `arche.link` once that's funded.
4. **Verify** — `arche.sign` + `arche.credentials` wrap results in Ed25519-signed JWS envelopes keyed by `did:key`. Recipients verify offline. SD-JWT-VC re-framing for wallet ecosystems.
5. **Govern** — `arche.policy` (statute YAMLs, six closed actions) + `arche.graph.audit` (append-only SQLite, JWS-signed regulator exports, PII never stored).

`arche.workflow.{Pipeline, DSARWorkflow}` composes the five lifecycle steps
into citizen-side and organisation-side flows.

## Need OCR or document parsing?

Examples here use plain strings. For PDFs / DOCX / scanned forms, install
the `[doc]` extra:

```bash
pip install arche-core[doc]       # PDF, DOCX, PPTX, XLSX (docling-backed)
pip install arche-core[doc-ocr]   # adds easyocr for scanned PDFs / images
```

Then use `Pipeline.process_file(path)` instead of `Pipeline.process(text)`.

## Legacy v0.1 example

[`identity_knowledge_graph.py`](identity_knowledge_graph.py) is a v0.1
example that uses the older `resolve()` function and visualization
output. It still works — the legacy `resolve()` callable remains
available — but new code should use the v0.2 `Pipeline` primitive
demonstrated above.
