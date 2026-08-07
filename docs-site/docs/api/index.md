# API Reference

The arche-core v0.2 public surface is intentionally slim. Everything below is importable from `arche`.

```python
from arche import Pipeline, Result, Detection
```

For the deeper substrate APIs, import from the substrate package directly; hand-maintained reference pages below cover every documented surface, and the [source on GitHub](https://github.com/unpatterned-labs/arche/tree/main/packages/arche-core/src/arche) is the last word.

---

## Core surface (PRD §10.1)

| Symbol | Purpose | Page |
|---|---|---|
| `Result` | Typed return from `Pipeline.process(...)` | pipeline.md |
| `Detection` | A single detected PII span with category, span, confidence | pipeline.md |
| [`detect`](detect.md) | The Level-2 workhorse functions | per-page |
| [`resolve.pairwise` / `resolve.crosswalk` / `sign_edges`](crosswalk.md) | Entity resolution: signable pairwise decisions + list-scale crosswalks | crosswalk.md |
| [`extract_places` / `grade_places` / `PlaceMention`](addr.md) | Spatial role labeling + the shipped referee | addr.md |

Plus `__version__`. **v0.3 note:** the v0.1 callable `arche.resolve(text)` is removed; `arche.resolve` is the facade package documented on [crosswalk.md](crosswalk.md).

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

Statute YAMLs live at `arche/policy/statutes/`. Six packs at v1.0: NDPA-2023 (NG), POPIA (ZA), KENYA-DPA, GHANA-DPA, GDPR, HIPAA-SAFE-HARBOR. Every pack declares `review_status` (`self-reviewed` or `regulator-reviewed`) alongside `version`; the loader rejects a regulator-review claim with no named reviewer. Read it off `Statute.review_status`.

### Address & spatial roles — `arche.addr`

```python
from arche.addr import parse_address, parse_addresses, extract_anchor
from arche.addr import extract_places, grade_places, load_gold, load_role_pack
```

NG/ZA/KE/GH + UK address parsing with landmark anchors, plus spatial role labeling (origin/destination/location/via with cue evidence) and the shipped gold set + refusal-aware grader. Full reference: [addr.md](addr.md).

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
from arche.resolve import pairwise, crosswalk, ENTITY_PACKS
from arche.resolve.reconcile import reconcile, sign_edges
```

The documented front door has two entry points by use-shape: `pairwise(a, b)` — "are these two the same?" (Fellegi–Sunter + gate, signable `CoReferenceDecision`) — and `crosswalk(list_a, list_b)` — link two lists at scale (union blocking + gate + evidence, per-edge `decision_id`, `sign_edges`). Full reference: [crosswalk.md](crosswalk.md).

The legacy classical surface (`resolve_entities`, `resolve_identity_records`, `ResolvedEntity` — fuzzy Fellegi–Sunter with African-name equivalence, optional Splink backend via `arche-core[resolve]`) remains importable; see the [entity resolution tutorial](../tutorials/entity_resolution.md).

### Declarations — `arche.declare`

```python
from arche.declare import Declaration, DeclarationError

decl = Declaration.from_yaml("fisheries.decl.yaml")
decl.pin()            # "name@version:sha256:<16 hex>" — enters every decision_id
decl.comparators()    # the generated entity pack for crosswalk(decl=...)
decl.json_schema()    # the extraction contract for any LLM (additionalProperties: false)
decl.tool_def("anthropic")   # or "openai" / "json-schema"
```

One YAML declares the user's fields and their roles (`identifies` / `describes` / `ignore`, kinds, `restricted`, statute classes); everything downstream generates from it. Guide: [Declare your schema](../how-to/declare-your-schema.md).

### LLM lane — `arche.llm`

```python
from arche.llm import LLMConfig, extract_declared, extract_places_llm
from arche.llm import grade_pairs, grade_extractions
```

Models propose, the engine verifies: declaration-driven extraction (`extract_declared`), cue-verified spatial role proposals (`extract_places_llm`), and the harness that grades a judge against the deterministic engine (`grade_pairs`). Guides: [Bring your own LLM](../how-to/bring-your-own-llm.md), [Extract places](../how-to/extract-places-with-roles.md).

---

## See also

- [Quick Start](../getting-started/quickstart.md) — five copy-paste examples.
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md) — persona guide + cross-tool benchmark.
