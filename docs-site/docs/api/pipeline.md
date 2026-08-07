# Pipeline

`Pipeline` is the v0.2 framework primitive. A single `Pipeline.process(text)` call composes detection + jurisdiction-aware policy + audit and returns a typed `Result`.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process(
    "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
)

print(result.redacted_text)
# Customer NAME_..., NIN [NIN], phone PHONE_...
```

---

## `Pipeline`

```python
class Pipeline:
    def __init__(
        self,
        jurisdiction: str | None = None,
        statute: str | None = None,
        detectors: list[str] | None = None,
        address_parsing: bool = False,
        audit: bool = True,
        tokenize_salt: str = "",
    ) -> None: ...

    def process(self, text: str) -> Result: ...
    def process_file(self, source: str | Path) -> Result: ...
    def describe(self) -> dict[str, Any]: ...
```

Source: [`packages/arche-core/src/arche/workflow/_primitive.py`](https://github.com/unpatterned-labs/arche/blob/main/packages/arche-core/src/arche/workflow/_primitive.py).

### Constructor parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | `str \| None` | `None` | ISO-3166-1 alpha-2 country code (`"NG"`, `"KE"`, `"ZA"`, `"GH"`). Auto-loads the matching statute via `_STATUTE_FOR_JURISDICTION`. Uppercased internally. |
| `statute` | `str \| None` | `None` | Explicit statute YAML name (`"NDPA-2023"`, `"POPIA"`, `"KENYA-DPA"`, `"GHANA-DPA"`). Overrides the jurisdiction-implied statute. If neither `jurisdiction` nor `statute` is given, no policy is applied and raw detections are returned. |
| `detectors` | `list[str] \| None` | `None` | Which detector packages to run. When omitted and `jurisdiction` is set, defaults to `["<cc>", "names", "locations", "ip", "digital_id", "addr", "core"]`. When `jurisdiction` is missing, defaults to `["africa", "names", "locations", "ip", "digital_id", "addr", "core"]`. |
| `address_parsing` | `bool` | `False` | Forward-compatibility hook for `arche.addr.parse_address`. The `"addr"` detector package already runs by default; this flag is reserved for future opt-in semantics. |
| `audit` | `bool` | `True` | When `True`, emit per-detection and per-policy-decision entries into `Result.audit_log`. PII values are never recorded — only category labels, span offsets, document hashes, statute references, and timestamps. |
| `tokenize_salt` | `str` | `""` | Per-deployment salt for the `tokenize` policy action. Different salts across organisations prevent token re-identification when redacted documents cross trust boundaries. Pass a stable per-org secret from your environment, not a literal. |

### Methods

#### `process(text: str) -> Result`

Run the configured detector chain, apply the loaded statute's policy mappings, and (when `audit=True`) record per-event audit rows. Returns a `Result` dataclass.

The internal pipeline runs in five phases (per the source): detect → statute-aware enrichment (populates `sensitivity_tier` + `regulatory_citation` on each `Detection`) → address parsing hook → policy enforcement → in-memory audit recording.

#### `process_file(source: str | Path) -> Result`

Convenience: parse a file via `arche.doc.parse` (PDF / DOCX / PPTX / XLSX / HTML via docling — requires `arche-core[doc]`) then run `process()` on the extracted text. The returned `Result` carries `metadata["source_file"]` and `metadata["num_pages"]` for provenance.

Raises `DoclingNotInstalledError` (from `arche.doc`) if the optional extra is not installed.

#### `describe() -> dict[str, Any]`

Return a structured description of what this pipeline will do. Useful for logging / introspection — the dict carries `jurisdiction`, `statute`, `detectors`, `address_parsing`, `audit`.

```python
pipeline = Pipeline(jurisdiction="NG", tokenize_salt="bank_2026")
pipeline.describe()
# {
#   "jurisdiction": "NG",
#   "statute": "NDPA-2023",
#   "detectors": ["ng", "names", "locations", "ip", "digital_id", "addr", "core"],
#   "address_parsing": False,
#   "audit": True,
# }
```

---

## `Result`

```python
@dataclass
class Result:
    document_hash: str
    detections: list[Detection]
    addresses: list[Any]                   # arche.addr.Address (forward-compat)
    policy_outcomes: list[PolicyOutcome]   # arche.policy.PolicyOutcome
    redacted_text: str
    audit_log: list[dict]                  # PII-free per-event rows
    metadata: dict[str, Any]
```

`Result` is a plain `@dataclass` with no instance methods. Read fields directly, or serialize the whole thing with `dataclasses.asdict` — see the [Output Formats guide](../guides/output-formats.md) for the canonical JSON / CSV / Pydantic projection patterns.

### Field reference

| Field | Type | What's in it |
|---|---|---|
| `document_hash` | `str` | SHA-256 hex of the input text (UTF-8). Used as the join key in the audit log so PII values never have to be stored. |
| `detections` | `list[Detection]` | Every detection the configured detector chain emitted, enriched with `sensitivity_tier` + `regulatory_citation` from the loaded statute. |
| `addresses` | `list[Address]` | Reserved for forward-compatibility. Address detections currently surface as `Detection` rows with `category="PII-4-ADDRESS"`; this list is empty in v0.2.0a3. |
| `policy_outcomes` | `list[PolicyOutcome]` | One row per detection that the statute mapped to a closed action (`mask` / `tokenize` / `drop` / `generalize` / `audit` / `retain`). Carries `category`, `action`, `statute_id`, `statute_reference`, `span`, `detection_id`. |
| `redacted_text` | `str` | The input text after policy actions have been applied. Safe to log, share, or persist. |
| `audit_log` | `list[dict]` | When `audit=True`, one dict per detection event (`event_type="detection"`) and one per policy decision (`event_type="policy"`). PII-free by construction — category labels, span offsets, document hash, statute reference. Each dict also has `timestamp` (ISO 8601 UTC). |
| `metadata` | `dict[str, Any]` | Pipeline configuration snapshot: `jurisdiction`, `statute_id`, `statute_version`, `detectors`, `address_parsing`, `audit`, `pipeline_version`. When `process_file` was used, also `source_file` and `num_pages`. |

### Persisting the audit log to SQLite

`Pipeline` builds `Result.audit_log` as an in-memory list of plain dicts. Persisting to SQLite is the caller's job — wire it via the `arche.graph.audit` substrate:

```python
from arche.graph.audit import AuditEvent, AuditLog

audit = AuditLog("./compliance.sqlite")

def record_result(audit: AuditLog, result, document_id: str) -> None:
    for d in result.detections:
        audit.emit(AuditEvent.detection(
            document_hash=document_id, category=d.category,
            span=(d.start, d.end), confidence=d.confidence, detector=d.detector,
        ))
    for o in result.policy_outcomes:
        audit.emit(AuditEvent.policy(
            document_hash=document_id, category=o.category, action=o.action,
            statute_id=o.statute_id, statute_reference=o.statute_reference,
            detection_id=o.detection_id, span=o.span,
        ))

for text in batch_of_documents:
    result = pipeline.process(text)
    record_result(audit, result, document_id=result.document_hash)
```

This is the same pattern the cookbooks use — see [Nigerian fintech KYC](../cookbooks/fintech-kyc.md) and [SQLite audit log example](https://github.com/unpatterned-labs/arche/blob/main/examples/05_audit_log.py).

---

## `Detection`

```python
@dataclass
class Detection:
    id: str
    category: str
    text: str
    start: int
    end: int
    confidence: float
    detector: str
    identity_class: str = "inferred"
    sensitivity_tier: SensitivityTier = SensitivityTier.MODERATE
    regulatory_citation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Field reference

| Field | Type | What's in it |
|---|---|---|
| `id` | `str` | Stable identifier for cross-referencing in `policy_outcomes` and `audit_log`. Shape: `det:<start>:<end>`. |
| `category` | `str` | Pan-African PII Taxonomy v0.1 label — e.g. `"PII-2-NIN"`, `"PII-1-NAME"`, `"PII-3-PHONE"`, `"PII-4-ADDRESS"`, `"PII-5-CRYPTO_WALLET"`. |
| `text` | `str` | The actual matched substring from the input. The original PII value — keep this off your wire and out of your logs. |
| `start` | `int` | Inclusive character offset into the input text. |
| `end` | `int` | Exclusive character offset. |
| `confidence` | `float` | `1.0` for structurally validated detections (Luhn-checked SA ID, NIN pattern + length + prefix). Lower for shape-only matches. |
| `detector` | `str` | Producer string — e.g. `"rule:ng_nin"`, `"phonenumbers:NG"`, `"rule:addr_parser"`, `"gliner"` when the optional `[detect]` extra is active. |
| `identity_class` | `str` | One of `foundational` / `functional` / `federated` / `inferred` — the four-class identity-class distinction from the Pan-African PII Taxonomy. |
| `sensitivity_tier` | `SensitivityTier` | `HIGH` / `MODERATE` / `LOW`, populated from the loaded statute at detection time. Defaults to `MODERATE` for standalone detector calls that bypass `Pipeline` (no statute loaded means no tier mapping). |
| `regulatory_citation` | `str \| None` | The specific statute section (`"NDPA-2023 s.29"`, `"NDPA-2023 s.30, NIMC Act s.27"`) the loaded statute cites for this category. `None` for standalone detector calls. |
| `metadata` | `dict[str, Any]` | Detector-specific extras. For `addr` detections: `street`, `city`, `region`, `country`. For per-country IDs: whatever the country-specific detector chose to expose (varies — see the relevant `arche.detect.<cc>` module). |

Reading the tier + citation that v0.2 ships:

```python
for d in result.detections:
    print(f"{d.category:18} {d.sensitivity_tier.value:8} {d.regulatory_citation}")
# PII-2-NIN          high     NDPA-2023 s.30, NIMC Act s.27
# PII-2-BVN          high     NDPA-2023 s.30, CBN BVN policy 2014
# PII-1-NAME         moderate NDPA-2023 s.30
```

---

## Examples

### Basic NDPA-2023 pipeline

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process("NIN 12345678901, BVN 22156789012.")

print([d.category for d in result.detections])
# ['PII-2-NIN', 'PII-2-BVN']

print(result.redacted_text)
# NIN [NIN], BVN [BVN].
```

### Inspect what the pipeline will do

```python
pipeline = Pipeline(jurisdiction="ZA", tokenize_salt="hospital_2026")
print(pipeline.describe())
# {
#   "jurisdiction": "ZA",
#   "statute": "POPIA",
#   "detectors": ["za", "names", "locations", "ip", "digital_id", "addr", "core"],
#   "address_parsing": False,
#   "audit": True,
# }
```

### Persisted audit log + signed regulator export

```python
from datetime import datetime
from arche import Pipeline
from arche.graph.audit import AuditEvent, AuditLog
from arche.sign import generate_keypair

audit = AuditLog("./compliance.sqlite")
pipeline = Pipeline(jurisdiction="NG", tokenize_salt="bank_2026")

def record_result(audit, result, document_id):
    for d in result.detections:
        audit.emit(AuditEvent.detection(
            document_hash=document_id, category=d.category,
            span=(d.start, d.end), confidence=d.confidence, detector=d.detector,
        ))
    for o in result.policy_outcomes:
        audit.emit(AuditEvent.policy(
            document_hash=document_id, category=o.category, action=o.action,
            statute_id=o.statute_id, statute_reference=o.statute_reference,
            detection_id=o.detection_id, span=o.span,
        ))

for text in batch_of_documents:
    result = pipeline.process(text)
    record_result(audit, result, document_id=result.document_hash)

officer_key = generate_keypair()
report = audit.export_signed(
    key=officer_key,
    purpose="ndpc_quarterly_audit",
    since=datetime(2026, 4, 1),
    until=datetime(2026, 6, 30),
)
# `report` is a JWS-signed bundle the regulator can verify offline.
```

### Pipeline + docling file ingest

```python
# requires: pip install arche-core[doc]
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")
print(f"{len(result.detections)} detections")
print(result.metadata["source_file"], result.metadata["num_pages"])
```

`Result` is a plain dataclass — for JSON / CSV / Pydantic serialization patterns, see the [Output Formats guide](../guides/output-formats.md).

---

_Verified against `arche-core` v0.2.0a3 on 2026-05-29. Constructor signature, `Result` dataclass fields, `Detection` dataclass fields, and the absence of `Result` methods all confirmed against [`packages/arche-core/src/arche/workflow/_primitive.py`](https://github.com/unpatterned-labs/arche/blob/main/packages/arche-core/src/arche/workflow/_primitive.py)._

---

## See also

- [Output Formats](../guides/output-formats.md) — JSON / CSV / Pydantic projection patterns for `Result`.
- [Architecture](../concepts/architecture.md) — how `Pipeline` composes with the other substrates.
- [How arche Works](../concepts/how-it-works.md) — substrate-by-substrate walkthrough.
- [Power-user: Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Power-user: Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
- [Roadmap](../concepts/roadmap.md) — where the API goes next.
