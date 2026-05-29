# API Reference

The arche-core v0.2 public surface is intentionally slim. Everything below is importable from `arche`.

```python
from arche import Pipeline, Result, Detection
```

For the deeper substrate APIs, import from the substrate package directly. For exhaustive auto-generated reference, see the [source on GitHub](https://github.com/unpatterned-labs/arche/tree/main/packages/arche-core/src/arche) — the v0.2.0a3 release introduces `mkdocstrings`-rendered API pages.

---

## v0.2 surface (PRD §10.1)

| Symbol | Purpose | Page |
|---|---|---|
| [`Pipeline`](pipeline.md) | The framework primitive — detect + policy + audit in one call | pipeline.md |
| `Result` | Typed return from `Pipeline.process(...)` | pipeline.md |
| `Detection` | A single detected PII span with category, span, confidence | pipeline.md |

Plus `__version__`.

---

## Substrate APIs

### Detect — `arche.detect`

```python
from arche.detect.ng.ids import detect_nigerian_ids
from arche.detect.ke.ids import detect_kenyan_ids
from arche.detect.za.ids import detect_south_african_ids
from arche.detect.gh.ids import detect_ghanaian_ids
from arche.detect._africa.ids import detect_african_ids
from arche.detect._africa.phones import normalize_e164, validate_phone
```

Per-country ID detectors return `list[Detection]`. Phone helpers wrap `phonenumbers` (libphonenumber port) for E.164 normalization.

### Policy — `arche.policy`

```python
from arche.policy import (
    load_statute,
    apply_policy,
    list_available_statutes,
)
```

Statute YAMLs live at `arche/policy/statutes/`. Four launch jurisdictions: NDPA-2023 (NG), POPIA (ZA), KENYA-DPA, GHANA-DPA.

### Address — `arche.addr`

```python
from arche.addr import parse_address
```

NG + ZA address parser MVP (Stage 1). KE + GH coverage arrives in v0.3 per FR-ADDR-1..10.

### Sign + Credentials — `arche.sign`, `arche.credentials`

```python
from arche.sign import (
    generate_keypair,
    SignWorkflow,
    VerifyExtractWorkflow,
    ArcheSignedDocument,
)
from arche.credentials.sd_jwt import (
    issue_sd_jwt,
    verify_sd_jwt,
    present,
    envelope_to_sd_jwt,
)
```

Ed25519 + did:key + JWS. SD-JWT-VC for wallet ecosystem interop (EUDI Wallet ARF / MOSIP Inji format).

### Audit — `arche.graph.audit`

```python
from arche.graph.audit import AuditLog, AuditEvent
```

SQLite-backed append-only log. PII values never stored — only category labels, spans, document hashes. Signed export bundles for regulator handoff. See PRD §8.2.

### Workflows — `arche.workflow`

```python
from arche.workflow import Pipeline, Result, Detection
from arche.workflow.dsar import DSARWorkflow
```

`Pipeline` composes Detect → Policy → Audit. `DSARWorkflow` is the citizen-side Data Subject Access Request drafter for NDPA / POPIA / Kenya DPA / Ghana DPA.

### Document ingest — `arche.doc` (optional)

```python
from arche.doc import parse  # requires arche-core[doc]
```

docling-backed PDF/DOCX/PPTX/XLSX/HTML parser. `Pipeline.process_file(path)` delegates to this substrate.

### Entity resolution — `arche.resolve`

```python
from arche.resolve import (
    resolve_entities,
    resolve_identity_records,
    ResolvedEntity,
)
```

Fuzzy Fellegi-Sunter with African-name equivalence by default. With `arche-core[resolve]` installed, transparently engages a Splink+DuckDB backend at sizes >=10 entities. A first-class `SplinkResolver` user class arrives in v0.3. See the [entity resolution tutorial](../tutorials/entity_resolution.md).

---

# v0.2
from arche import Pipeline
result = Pipeline(jurisdiction="NG").process(text)
```

See the [Quick Start](../getting-started/quickstart.md) and [HOW-TO §10](https://github.com/unpatterned-labs/arche/blob/main/HOW-TO.md#10-whats-deferred-to-stage-2) for the full migration walk-through.
