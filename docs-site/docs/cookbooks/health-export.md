# Cookbook — South African POPIA-compliant clinical export

You work on a clinical data platform serving a network of public hospitals in South Africa. A university epidemiology research group has contracted with your provincial health authority to study a population-level health outcome and needs anonymised patient records to do it. POPIA Section 32 (special-category data — health, biometric) requires that you remove direct identifiers before the data leaves your perimeter; POPIA Section 71 lets you share processed data for research subject to safeguards. The CISO wants an audit trail proving the de-identification happened, with the statute section attached to every redaction. The researcher wants the cleanest possible signal in the cohort fields.

*(This cookbook describes an illustrative workflow. Substitute your real research partner, jurisdiction-of-operation hospital network, and study design — the pattern stays the same.)*

**Before arche-core:** your team built a stored procedure that scrubs SA IDs and addresses using regex, but it doesn't validate the Luhn checksum (so it misses transcribed-wrong IDs that still look like IDs) and it doesn't know what statute applies. You email the CSV to the researcher; the CISO asks who can prove what was redacted; nobody answers cleanly.

**With arche-core:** Pipeline with `jurisdiction="ZA"` knows POPIA, knows the SA ID format (Luhn validated + DOB / gender / citizenship decode), knows landmark-anchored ZA addresses, and attaches the POPIA section to every redaction.

```python
from arche import Pipeline
from arche.graph.audit import AuditEvent, AuditLog

pipeline = Pipeline(jurisdiction="ZA")   # auto-loads POPIA
audit = AuditLog("./gauteng_health_export.sqlite")


def record_result(audit: AuditLog, result, document_id: str) -> None:
    """Persist a Pipeline Result into the SQLite audit log.

    PII values are never stored — only category labels, span offsets,
    document hashes (PRD §8.2).
    """
    for d in result.detections:
        audit.emit(AuditEvent.detection(
            document_hash=document_id,
            category=d.category,
            span=(d.start, d.end),
            confidence=d.confidence,
            detector=d.detector,
        ))
    for o in result.policy_outcomes:
        audit.emit(AuditEvent.policy(
            document_hash=document_id,
            category=o.category,
            action=o.action,
            statute_id=o.statute_id,
            statute_reference=o.statute_reference,
            detection_id=o.detection_id,
            span=o.span,
        ))


def deid_record(record: ClinicalRecord) -> ResearcherSafeRecord:
    text = "\n".join([
        f"Patient: {record.full_name}",
        f"SA ID: {record.sa_id}",
        f"Address: {record.home_address}",
        f"Phone: {record.contact_phone}",
        f"Visit notes: {record.clinical_notes}",
    ])
    result = pipeline.process(text)
    record_result(audit, result, document_id=record.encounter_id)
    return ResearcherSafeRecord(
        encounter_id=record.encounter_id,
        redacted_text=result.redacted_text,
        # Cohort fields the researcher needs, computed from PII-free metadata
        age_band=record.age_band,           # already bucketed upstream
        diagnosis_icd10=record.diagnosis,   # not PII under POPIA s.32
        outcome=record.outcome,
    )
```

On a synthetic record like *"Patient: [SYNTHETIC TEST PATIENT] / SA ID: 9001011234084 / Address: 1 Example Road, Soweto / Phone: +27 11 555 0123"* the v0.2.0a3 detector chain emits:

```
PII-2-NATIONAL_ID  "9001011234084"          POPIA s.26 (special personal information — biometric)
PII-4-LOCATION     "Soweto"                 POPIA s.11
PII-4-ADDRESS      "1 Example Road, Soweto" POPIA s.11
```

The SA ID detector ran a Luhn checksum on `9001011234084` (a synthetic test value, not a real person's ID) and masked it; the address parser recognised the landmark format; the Soweto gazetteer hit fired the location detector. Every detection carries the POPIA section the policy mapping cites. Use clearly-synthetic test data when documenting workflows — never paste real patient PII into examples, training material, or test fixtures.

The shipped detector chain is conservative on personal names — the African names lexicon (114 equivalence groups) catches many common given names but won't catch every patient name. If you need name-level coverage, layer in GLiNER2-PII via `pip install arche-core[detect]` and re-run; the additional detections flow through the same `record_result` helper.

## What the researcher gets

```python
batch = [deid_record(r) for r in encounters]
export_csv(batch, "/data/exports/research_cohort_2026q2.csv")
```

The export file has the redacted notes plus the cohort fields. No SA IDs. No addresses. No names. Diagnosis codes and outcome categories — the actual research signal — pass through unchanged because they're not PII under POPIA.

## What the CISO gets

The audit SQLite database recorded every detection and policy decision. When the Information Regulator asks *"what was shared with the research group last quarter?"* the compliance officer runs:

```python
from datetime import datetime

from arche.sign import generate_keypair

report = audit.compliance_report_markdown(
    since=datetime(2026, 4, 1),
    until=datetime(2026, 6, 30),
)

officer_key = generate_keypair()    # or load from your KMS
bundle = audit.export_signed(
    key=officer_key,
    purpose="research_export_2026q2",
    since=datetime(2026, 4, 1),
    until=datetime(2026, 6, 30),
)
```

`compliance_report_markdown` returns a string with category counts grouped by `(statute, category, action)`, the statute reference that gated each action, and the distinct document hashes touched in the window — without ever displaying a single SA ID. `export_signed` wraps the same event window in a JWS envelope the Information Regulator verifies offline against the compliance officer's `did:key`.

`since=` and `until=` take `datetime` objects (not strings) because the comparison is performed against the ISO-8601 UTC timestamps the audit log writes per row.

## When this pattern doesn't fit

This cookbook assumes record-level de-identification before export. If your use case is *aggregation* (counts, summary statistics) rather than record-level, you don't need arche-core at all — you need a stats query. If the researcher needs *linkable* records (the same patient identifiable across two longitudinal datasets), POPIA Section 32(3) gives you a path via pseudonymisation; that's where `Pipeline(tokenize_salt=...)` becomes the right tool: same patient → same token across exports, never reversible without the salt.

---

_Verified against `arche-core` v0.2.0a3 on 2026-05-29 in a clean Python 3.11 venv. The `Pipeline(jurisdiction="ZA")` chain, the `AuditEvent`-based audit emission, `compliance_report_markdown`, and `export_signed` calls run as shown. `ClinicalRecord` / `ResearcherSafeRecord` are illustrative DTOs in your application layer._

## See also

- [Cookbook — Nigerian fintech KYC](fintech-kyc.md) — same pattern, NDPA instead of POPIA
- [Power-user cookbook: Civil-society audit](civil-society-audit.md) — when the auditor is *outside* the organisation
- [Quick Start example 5 — SQLite audit log](../getting-started/quickstart.md#5-sqlite-audit-log-signed-regulator-export)
- [Power-user: Sign, share, extract](../tutorials/sign_share_extract.md) — signing exports across organisational boundaries
- [Roadmap](../concepts/roadmap.md)
