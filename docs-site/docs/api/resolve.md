# Pipeline

`Pipeline` is the v0.2 framework primitive. A single `Pipeline.process(text)` call composes detection + jurisdiction-aware policy + audit and returns a typed `Result`.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process(
    "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
)

print(result.redacted_text)
# Customer Adesola Okonkwo, NIN [NIN], phone PHONE_d3100c11.
```

(`Adesola Okonkwo` survives here because the base-install name detector is
lexicon-driven and this pair is not in the lexicon. Names that are - e.g.
`Fatima Abdullahi` - redact to `NAME_<token>`.)

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
        overlays: list[str] | None = None,
        transparency_notice: str | None = None,
    ) -> None: ...

    def process(self, text: str) -> Result: ...
    def process_file(self, source: str | Any) -> Result: ...
```

### Constructor parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | `str \| None` | `None` | ISO-3166-1 alpha-2 country code (`"NG"`, `"KE"`, `"ZA"`, `"GH"`). Auto-loads the matching statute. |
| `statute` | `str \| None` | `None` | Explicit statute YAML name (`"NDPA-2023"`, `"POPIA"`, `"KENYA-DPA"`, `"GHANA-DPA"`). Overrides `jurisdiction`. |
| `detectors` | `list[str] \| None` | `None` | Restrict the detector chain. `None` selects the set implied by the jurisdiction. |
| `address_parsing` | `bool` | `False` | Enable the address parser (NG + ZA MVP). |
| `audit` | `bool` | `True` | Emit audit rows onto `result.audit_log`. Set `False` to skip. |
| `tokenize_salt` | `str` | `""` | Per-org secret mixed into `tokenize` placeholders so tokens are stable within your org and unlinkable across orgs. |
| `overlays` | `list[str] \| None` | `None` | Extra policy overlays layered onto the statute. |
| `transparency_notice` | `str \| None` | `None` | Notice text recorded alongside the run. |

There is **no `audit_log=` parameter.** `Pipeline` does not take an `AuditLog`
instance and does not write to SQLite. It emits audit rows onto
`result.audit_log` (a `list[dict]`); persisting them is a separate, explicit
step - see [Persisted audit log](#persisted-audit-log-signed-regulator-export)
below.

At least one of `jurisdiction` or `statute` must be supplied.

### Methods

#### `process(text: str) -> Result`

Run the substrate chain on a string. Returns a `Result` with detections, policy outcomes, redacted text, and audit entries.

#### `process_file(source: str | Any) -> Result`

The parameter is named `source`, not `path`.

Convenience: parse a file via `arche.doc.parse` (PDF/DOCX/PPTX/XLSX via docling - requires `arche-core[doc]`) then run `process()` on the extracted text.

---

## `Result`

```python
@dataclass
class Result:
    document_hash: str                    # SHA-256 of the input
    detections: list[Detection]           # Every category match (pre-policy)
    addresses: list[Any]                  # Parsed addresses when address_parsing=True
    policy_outcomes: list[PolicyOutcome]  # Action + statute citation per detection
    redacted_text: str                    # After applying policy
    audit_log: list[dict]                 # PII-free audit rows
    metadata: dict                        # Jurisdiction, statute id/version, detectors, ...
```

### Methods

`Result` is a plain dataclass. It has **no methods** - no `to_dict()`,
`to_json()`, or `summary()`. It also does not carry the original `text`, an
`entities` list, an `audit_entries` list, or the loaded `statute`; the
seven fields above are the whole surface.

For a per-category / per-action rollup, count over the lists yourself:

```python
from collections import Counter
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
)
print(Counter(d.category for d in result.detections))
print(Counter(o.action for o in result.policy_outcomes))
# Counter({'PII-2-NIN': 1, 'PII-3-PHONE': 1})
# Counter({'mask': 1, 'tokenize': 1})
```

To serialise, use `dataclasses.asdict(result)` or build the dict you want.
The loaded statute is identified in `result.metadata["statute_id"]` /
`["statute_version"]`, and reloadable with `arche.policy.load_statute(...)`.

---

## `Detection`

```python
@dataclass
class Detection:
    id: str                   # e.g. "det:nin:30:41"
    category: str             # Pan-African PII Taxonomy label, e.g. "PII-2-NIN"
    text: str                 # The RAW matched substring
    start: int                # Inclusive character offset
    end: int                  # Exclusive character offset
    confidence: float
    detector: str             # e.g. "rule:ng_nin", "rule:phone_libphonenumber"
    identity_class: str = "inferred"
    sensitivity_tier: SensitivityTier = SensitivityTier.MODERATE
    regulatory_citation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

!!! danger "`Detection.text` holds the raw PII value"

    `Detection` **does** retain the original value. There is no
    `value_redacted` field; the placeholder that appears in
    `result.redacted_text` lives on the corresponding
    `PolicyOutcome.applied_value`.

    ```python
    result = Pipeline(jurisdiction="NG").process(
        "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
    )
    print(result.detections[0].text)
    # 12345678901        <- the real NIN, in the clear
    ```

    `result.detections` is therefore **not** a PII-free artifact. Keep this off
    your wire and out of your logs. The PII-free artifacts are
    `result.redacted_text` and `result.audit_log`.

---

## Examples

### Basic NDPA-2023 pipeline

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process("NIN 12345678901, BVN 22156789012.")
print([d.category for d in result.detections])
# ['PII-2-BVN', 'PII-2-NIN']
print(result.redacted_text)
# NIN [NIN], BVN [BVN].
```

### Persisted audit log + signed regulator export

`Pipeline` does not write to the audit log for you. Build `AuditEvent` objects
from the result and hand them to `AuditLog.emit_many()`:

```python
from arche import Pipeline
from arche.graph.audit import AuditLog, AuditEvent
from arche.sign import generate_keypair

audit = AuditLog("./compliance.sqlite")
pipeline = Pipeline(jurisdiction="NG")

for text in batch_of_documents:
    result = pipeline.process(text)
    audit.emit_many(
        AuditEvent.detection(
            document_hash=result.document_hash,
            detection_id=d.id,
            category=d.category,
            span=(d.start, d.end),
            confidence=d.confidence,
            detector=d.detector,
        )
        for d in result.detections
    )
    audit.emit_many(
        AuditEvent.policy(
            document_hash=result.document_hash,
            detection_id=o.detection_id,
            category=o.category,
            action=o.action,
            statute_id=o.statute_id,
            statute_reference=o.statute_reference,
            span=o.span,
        )
        for o in result.policy_outcomes
    )

officer_key = generate_keypair()
report = audit.export_signed(key=officer_key, purpose="ndpc_quarterly_audit")
# `report` is a JWS-signed compact string the regulator can verify offline.
```

`result.audit_log` is a `list[dict]`, not `list[AuditEvent]` - passing it
straight to `emit_many()` raises `AttributeError`. `AuditEvent.detection` and
`AuditEvent.policy` are the supported constructors, and all their parameters are
keyword-only. `export_signed`'s `since` / `until` take `datetime` objects, not
date strings.

### Pipeline + docling file ingest

```python
# requires: pip install arche-core[doc]
from collections import Counter
from arche import Pipeline

pipeline = Pipeline(jurisdiction="ZA")
result = pipeline.process_file("dsar_response.pdf")
print(Counter(d.category for d in result.detections))
```

---

## See also

- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [Citizen DSAR tutorial](../tutorials/citizen_dsar.md)
