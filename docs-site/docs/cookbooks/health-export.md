# Cookbook — South African POPIA-compliant clinical export

You work on a clinical data platform serving public hospitals in Gauteng. A team of epidemiology researchers at Wits University needs anonymised patient records to study post-COVID respiratory outcomes. POPIA Section 32 (special-category data — health, biometric) requires that you remove direct identifiers before the data leaves your perimeter; POPIA Section 71 lets you share processed data for research. The CISO wants an audit trail proving the de-identification happened, with the statute section attached to every redaction. The researcher wants the cleanest possible signal in the cohort fields.

**Before arche-core:** your team built a stored procedure that scrubs SA IDs and addresses using regex, but it doesn't validate the Luhn checksum (so it misses transcribed-wrong IDs that still look like IDs) and it doesn't know what statute applies. You email the CSV to the researcher; the CISO asks who can prove what was redacted; nobody answers cleanly.

**With arche-core:** Pipeline with `jurisdiction="ZA"` knows POPIA, knows the SA ID format (Luhn validated + DOB / gender / citizenship decode), knows landmark-anchored ZA addresses, and attaches the POPIA section to every redaction.

```python
from arche import Pipeline
from arche.graph.audit import AuditLog

pipeline = Pipeline(jurisdiction="ZA")   # auto-loads POPIA
audit = AuditLog("./gauteng_health_export.sqlite")

def deid_record(record: ClinicalRecord) -> ResearcherSafeRecord:
    text = "\n".join([
        f"Patient: {record.full_name}",
        f"SA ID: {record.sa_id}",
        f"Address: {record.home_address}",
        f"Phone: {record.contact_phone}",
        f"Visit notes: {record.clinical_notes}",
    ])
    result = pipeline.process(text)
    audit.emit_pipeline_result(result, document_id=record.encounter_id)
    return ResearcherSafeRecord(
        encounter_id=record.encounter_id,
        redacted_text=result.redacted_text,
        # Cohort fields the researcher needs, computed from PII-free metadata
        age_band=record.age_band,           # already bucketed upstream
        diagnosis_icd10=record.diagnosis,   # not PII under POPIA s.32
        outcome=record.outcome,
    )
```

The detection set ends up looking like:

```
PII-1-NAME       "Thembi Mokoena"                  POPIA s.32 (special category)
PII-2-SA_ID      "8001015009087"                   POPIA s.32 + Identification Act 68 of 1997
PII-4-ADDRESS    "23 Vilakazi St, Soweto"          POPIA s.11 (lawful processing)
PII-3-PHONE      "+27 11 555 0123"                 POPIA s.11
```

The SA ID detector ran a Luhn checksum on `8001015009087`, decoded `1980-01-01 male SA citizen` (and stored none of that), then masked it. The address detector recognised the landmark format. Every detection carries the POPIA section the policy mapping cites.

## What the researcher gets

```python
batch = [deid_record(r) for r in encounters]
export_csv(batch, "/data/exports/wits_respiratory_2026q2.csv")
```

The export file has the redacted notes plus the cohort fields. No SA IDs. No addresses. No names. Diagnosis codes and outcome categories — the actual research signal — pass through unchanged because they're not PII under POPIA.

## What the CISO gets

The audit SQLite database recorded every detection and policy decision. When the Information Regulator asks "what was shared with Wits last quarter?" the compliance officer runs:

```python
report = audit.compliance_report_markdown(
    since="2026-04-01", until="2026-06-30",
    purpose="research_export"
)
```

The report shows: total records de-identified, category counts (NAME × 4,217, SA_ID × 4,217, ADDRESS × 3,890, PHONE × 2,104, …), the POPIA section that gated each action, and the document hashes — without ever displaying a single SA ID. The Information Regulator verifies the bundle against the compliance officer's `did:key` offline.

## When this pattern doesn't fit

This cookbook assumes record-level de-identification before export. If your use case is *aggregation* (counts, summary statistics) rather than record-level, you don't need arche-core at all — you need a stats query. If the researcher needs *linkable* records (the same patient identifiable across two longitudinal datasets), POPIA Section 32(3) gives you a path via pseudonymisation; that's where `Pipeline(tokenize_salt=...)` becomes the right tool: same patient → same token across exports, never reversible without the salt.

## See also

- [Cookbook — Nigerian fintech KYC](fintech-kyc.md) — same pattern, NDPA instead of POPIA
- [Power-user cookbook: Civil-society audit](civil-society-audit.md) — when the auditor is *outside* the organisation
- [Quick Start example 5 — SQLite audit log](../getting-started/quickstart.md#5-sqlite-audit-log-signed-regulator-export)
- [Power-user: Sign, share, extract](../tutorials/sign_share_extract.md) — signing exports across organisational boundaries
