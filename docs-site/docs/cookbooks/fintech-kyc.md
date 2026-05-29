# Cookbook — Nigerian fintech KYC intake

You're a backend engineer at a Lagos fintech. Customer onboarding writes a JSON record into your `intakes` table with the full customer profile — name, NIN, BVN, phone, address — and the data warehouse mirror picks it up. The CTO wants the mirror to carry redacted records only; the data team needs the *categories* of PII that were redacted (so they can model fraud risk on profile completeness) but never the values; and the NDPC will ask "show me the rule that decided each redaction" in the next audit.

**Before arche-core:** you wire Presidio (which doesn't know NIN from a US bank account), you write a 400-line `validators/ng.py` module that you'll maintain forever, you add another 200 lines of redaction logic, and you build a separate audit table you hope you remember to populate. Three engineering weeks. Bus factor of one. Auditor unhappy.

**With arche-core:** one Pipeline call.

```python
from arche import Pipeline

pipeline = Pipeline(
    jurisdiction="NG",
    tokenize_salt=settings.TOKENIZE_SALT,   # per-org secret from env
)

def redact_intake(intake_dict: dict) -> dict:
    text = format_intake_as_text(intake_dict)   # your concatenation helper
    result = pipeline.process(text)
    return {
        "redacted_text": result.redacted_text,
        "categories": [d.category for d in result.detections],   # data team gets this
        "statute_citations": [o.statute_reference for o in result.policy_outcomes],
        "audit_entries": result.audit_log,    # PII-free, by construction
    }
```

That's the whole feature. The detector chain inside Pipeline already knows about NIN (11 digits, NIMC spec), BVN (11 digits, 22-prefix, CBN policy), TIN, RC, voter PVC, driver's licence, phone numbers (libphonenumber-validated for Nigerian networks), and Nigerian names (via the 114-group lexicon).

## Wire it into the intake handler

Assuming a FastAPI / Django / Flask handler, the typical shape:

```python
from arche import Pipeline
from arche.graph.audit import AuditLog

pipeline = Pipeline(jurisdiction="NG", tokenize_salt=settings.TOKENIZE_SALT)
audit = AuditLog(settings.AUDIT_DB_PATH)   # SQLite file path

async def on_intake_received(intake: IntakeRecord) -> RedactedIntake:
    text = format_intake_as_text(intake)
    result = pipeline.process(text)
    audit.emit_pipeline_result(result, document_id=intake.id)
    return RedactedIntake(
        id=intake.id,
        redacted_text=result.redacted_text,
        category_counts=Counter(d.category for d in result.detections),
        statutes_applied=sorted(set(o.statute_reference for o in result.policy_outcomes)),
    )
```

`audit.emit_pipeline_result` writes every detection and policy decision into the SQLite log. PII values are never stored — only category labels, span offsets, document hashes (PRD §8.2).

## What goes to the warehouse, what stays out

The warehouse mirror gets `RedactedIntake`. The original `IntakeRecord` lives only in the encrypted intake store and is rotated out after 90 days per NDPA s.40 (data minimization). The fraud-modelling team gets `category_counts` and can train on *"customers with no BVN convert at X%, customers with NIN+BVN convert at Y%"* without ever touching a real BVN.

## The quarterly NDPC handoff

Three months later, the compliance officer needs to produce the audit. With the SQLite log already populated:

```python
from arche.sign import generate_keypair

officer_key = generate_keypair()    # or load from your KMS
bundle = audit.export_signed(
    key=officer_key,
    purpose="ndpc_audit_2026q2",
    since="2026-04-01",
    until="2026-06-30",
)
# Email the bundle (or upload to NDPC portal). The auditor verifies offline.
```

The bundle is a JWS envelope binding the audit rows + the statute version + the officer's `did:key`. The auditor verifies cryptographically that nothing changed since signing.

## What this gets you vs the alternatives

| Alternative | Where it falls short for NG KYC |
|---|---|
| Presidio default recognizers | Mislabels NIN as `US_BANK_NUMBER`. You write the NG recognizers anyway. |
| Presidio + custom NG recognizers | Solves detection. You still build statute citations, redaction policy, and audit log yourself. |
| GLiNER2-PII | Multilingual NER but no statute layer. You still build everything below detection. |
| OpenAI Privacy Filter | Closed-weight, non-auditable, requires API calls per record. Compliance regime rejects. |
| Hand-roll the whole thing | Three engineering weeks, bus factor one, no upstream maintenance when NIMC publishes amendments. |

## See also

- [Quick Start example 1 — Pipeline with NDPA-2023](../getting-started/quickstart.md#1-the-pipeline-primitive-ndpa-2023-enforcement-in-one-call)
- [Cookbook — Web URL → Detection](web-to-detection.md) — when intake comes from a public URL instead of a form
- [Power-user cookbook: South African health export](health-export.md) — same pattern, POPIA instead of NDPA
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md)
