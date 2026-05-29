# Output Formats

`Pipeline.process(text)` returns a `Result` — a plain dataclass you read directly or serialize with whichever encoder fits your stack. The framework deliberately does not impose an opinionated schema or a built-in serializer; the dataclass is the schema, and standard library tools handle the rest.

```python
from arche import Pipeline

result = Pipeline(jurisdiction="NG").process(
    "Fatima Abdullahi, NIN 12345678901, BVN 22100987654."
)
```

---

## The `Result` dataclass

| Field | Type | What's in it |
|---|---|---|
| `redacted_text` | `str` | Text after policy actions — safe to log or share |
| `detections` | `list[Detection]` | Every PII span the detector chain found |
| `policy_outcomes` | `list[PolicyOutcome]` | The action that was applied per category + the statute reference |
| `audit_log` | `list[AuditEvent]` | PII-free audit rows (only when `Pipeline(audit=True)`) |
| `document_hash` | `str` | SHA-256 of the original input |
| `metadata` | `dict` | Pipeline version, statute id and version, source file (when `process_file` was used) |

Each `Detection` carries `category`, `text`, `start`, `end`, `confidence`, `sensitivity_tier`, `regulatory_citation`, and `detector` (the producer name). Each `PolicyOutcome` carries `category`, `action`, `statute_id`, and `statute_reference`.

Read fields directly:

```python
print(result.redacted_text)
print(len(result.detections))
for d in result.detections:
    print(d.category, d.sensitivity_tier.value, d.regulatory_citation)
```

---

## JSON

`dataclasses.asdict` + `json.dumps` is the canonical path. No special encoder is needed because every field on `Result` is a dataclass, a primitive, or a list of them.

```python
import dataclasses
import json

payload = json.dumps(dataclasses.asdict(result), default=str, indent=2)
print(payload)
```

Pass `default=str` so `datetime` objects in the audit log serialize cleanly. Sample output (trimmed):

```json
{
  "redacted_text": "NAME_a3c1... NAME_b14d..., NIN [NIN], BVN [BVN].",
  "detections": [
    {
      "category": "PII-2-NIN",
      "text": "12345678901",
      "start": 26,
      "end": 37,
      "confidence": 1.0,
      "sensitivity_tier": "high",
      "regulatory_citation": "NDPA-2023 s.30, NIMC Act s.27",
      "detector": "rule:ng_nin"
    }
  ],
  "policy_outcomes": [
    {
      "category": "PII-2-NIN",
      "action": "mask",
      "statute_id": "NDPA-2023",
      "statute_reference": "NDPA-2023 s.30, NIMC Act s.27"
    }
  ],
  "document_hash": "3c1f9a...",
  "metadata": {
    "pipeline_version": "0.2.0a3",
    "statute_id": "NDPA-2023",
    "statute_version": "1.0"
  }
}
```

For API responses or storage you typically want a smaller projection — drop the audit log, drop the document hash if the consumer doesn't need it. Project the dict directly:

```python
api_payload = {
    "redacted_text": result.redacted_text,
    "categories": [d.category for d in result.detections],
    "statutes": [o.statute_reference for o in result.policy_outcomes],
}
```

---

## Python dict

If you want a dict for programmatic access without serializing, `dataclasses.asdict` gives you the same shape as JSON without the encoding step:

```python
import dataclasses

d = dataclasses.asdict(result)
print(d["detections"][0]["category"])
```

---

## CSV — detections as a table

CSV is one row per detection. Use `csv.DictWriter` with the fields you want:

```python
import csv
import dataclasses

with open("detections.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "document_hash", "category", "text",
        "start", "end", "confidence",
        "sensitivity_tier", "regulatory_citation", "detector",
    ])
    writer.writeheader()
    for d in result.detections:
        row = dataclasses.asdict(d)
        row["document_hash"] = result.document_hash
        row["sensitivity_tier"] = d.sensitivity_tier.value
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
```

Output:

```csv
document_hash,category,text,start,end,confidence,sensitivity_tier,regulatory_citation,detector
3c1f9a...,PII-2-NIN,12345678901,26,37,1.0,high,"NDPA-2023 s.30, NIMC Act s.27",rule:ng_nin
3c1f9a...,PII-2-BVN,22100987654,46,57,1.0,high,"NDPA-2023 s.30, CBN BVN policy 2014",rule:ng_bvn
```

For policy outcomes, same pattern with the `PolicyOutcome` fields. For audit log rows, `arche.graph.audit.AuditLog.compliance_report_markdown()` produces a markdown report directly; you rarely want raw audit CSV.

---

## Pydantic (when your API layer demands it)

If your FastAPI / Django Ninja / GraphQL layer expects Pydantic models rather than dataclasses, define your output schema once and project into it:

```python
from pydantic import BaseModel

class DetectionOut(BaseModel):
    category: str
    text: str
    sensitivity_tier: str
    regulatory_citation: str
    start: int
    end: int

class ResultOut(BaseModel):
    redacted_text: str
    detections: list[DetectionOut]

api_response = ResultOut(
    redacted_text=result.redacted_text,
    detections=[
        DetectionOut(
            category=d.category,
            text=d.text,
            sensitivity_tier=d.sensitivity_tier.value,
            regulatory_citation=d.regulatory_citation,
            start=d.start,
            end=d.end,
        )
        for d in result.detections
    ],
)
```

The Pipeline doesn't depend on Pydantic; the projection is yours.

---

## Signed JWS envelope (power-user)

When the output needs to cross a trust boundary — DSAR responses, regulator handoff bundles, KYC attestations — wrap the `Result` in a JWS envelope so the recipient can verify offline. See the [Power-user: Sign, share, extract](../tutorials/sign_share_extract.md) tutorial for the full chain. Short version:

```python
from arche.sign import SignWorkflow, generate_keypair

issuer = generate_keypair()
signed = SignWorkflow(jurisdiction="NG").sign(
    original_text, issuer, purpose="dsar_response"
)
# `signed` is a JWS compact string. Recipient verifies offline.
```

The signed envelope binds the document hash, the detections, the policy outcomes, and the statute version. No infrastructure required for verification — the `did:key` is embedded in the JWS header.

---

## Format choice — quick guide

| You want… | Use |
|---|---|
| In-memory access in Python | Read `result.<field>` directly |
| JSON for an API or storage | `json.dumps(dataclasses.asdict(result), default=str)` |
| A Pydantic model for FastAPI | Hand-project into your output schema as shown above |
| A row-per-detection table | `csv.DictWriter` over `result.detections` |
| A compliance report for an auditor | `arche.graph.audit.AuditLog.compliance_report_markdown()` |
| An offline-verifiable handoff | `arche.sign.SignWorkflow(...).sign(...)` |
