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
        audit_log: AuditLog | None = None,
    ) -> None: ...

    def process(self, text: str) -> Result: ...
    def process_file(self, path: str | Path) -> Result: ...
```

### Constructor parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | `str \| None` | `None` | ISO-3166-1 alpha-2 country code (`"NG"`, `"KE"`, `"ZA"`, `"GH"`). Auto-loads the matching statute. |
| `statute` | `str \| None` | `None` | Explicit statute YAML name (`"NDPA-2023"`, `"POPIA"`, `"KENYA-DPA"`, `"GHANA-DPA"`). Overrides `jurisdiction`. |
| `audit_log` | `AuditLog \| None` | `None` | Optional `arche.graph.audit.AuditLog` instance to record every detection. If `None`, audit entries are still produced on `result.audit_entries` but not persisted. |

At least one of `jurisdiction` or `statute` must be supplied.

### Methods

#### `process(text: str) -> Result`

Run the substrate chain on a string. Returns a `Result` with detections, policy outcomes, redacted text, and audit entries.

#### `process_file(path: str | Path) -> Result`

Convenience: parse a file via `arche.doc.parse` (PDF/DOCX/PPTX/XLSX via docling — requires `arche-core[doc]`) then run `process()` on the extracted text.

---

## `Result`

```python
@dataclass
class Result:
    text: str                          # Original input
    redacted_text: str                 # After applying policy
    detections: list[Detection]        # Every category match (pre-policy)
    policy_outcomes: list[PolicyOutcome]  # Action + statute citation per detection
    audit_entries: list[AuditEvent]    # PII-free audit rows
    statute: Statute                   # The loaded statute YAML
```

### Methods

| Method | Returns | Notes |
|---|---|---|
| `to_dict()` | `dict` | Plain-Python representation |
| `to_json(indent=2)` | `str` | JSON string |
| `summary()` | `dict` | Counts per category and per action |

---

## `Detection`

```python
@dataclass
class Detection:
    category: str        # Pan-African PII Taxonomy label, e.g. "PII-2-NIN"
    value_redacted: str  # Placeholder like "[NIN]"
    start: int           # Character offset
    end: int
    confidence: float    # 1.0 for structurally validated IDs
    country: str | None  # ISO-3166-1 alpha-2 when known
    source: str          # "regex" / "validator" / "gliner" / "_africa" / ...
```

`Detection.value_redacted` is the placeholder used in `result.redacted_text`. The original PII value is **not** retained on the Detection — `start`/`end` index into `result.text` if the caller still has it.

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

### Persisted audit log + signed regulator export

```python
from arche import Pipeline
from arche.graph.audit import AuditLog
from arche.sign import generate_keypair

audit = AuditLog("./compliance.sqlite")
pipeline = Pipeline(jurisdiction="NG", audit_log=audit)

for text in batch_of_documents:
    pipeline.process(text)

officer_key = generate_keypair()
report = audit.export_signed(key=officer_key, purpose="ndpc_quarterly_audit")
# `report` is a JWS-signed bundle the regulator can verify offline.
```

### Pipeline + docling file ingest

```python
# requires: pip install arche-core[doc]
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")
print(result.summary())
```

---

## See also

- [Architecture](../concepts/architecture.md) — the five substrates
- [How arche Works](../concepts/how-it-works.md) — substrate-by-substrate walkthrough
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
