# How to extract entities from an invoice

Run a Nigerian business invoice (PDF) through the v0.2 `Pipeline` and get back redacted text + a typed list of detections + a signed audit trail. Total time: ~30 seconds end-to-end.

```bash
pip install arche-core[doc]   # adds docling for PDF/DOCX/PPTX/XLSX
```

```python
from arche import Pipeline
from arche.graph.audit import AuditLog

audit = AuditLog("./invoice-audit.sqlite")
pipeline = Pipeline(jurisdiction="NG", audit_log=audit)

result = pipeline.process_file("invoice.pdf")
print(result.summary())
# {'PII-2-NIN': 1, 'PII-3-PHONE': 2, 'PII-4-EMAIL': 1, ...}

print(result.redacted_text)   # Safe to share with downstream consumers
```

---

## What gets detected

A standard Nigerian invoice typically surfaces:

| Field | Pan-African PII Taxonomy category |
|---|---|
| Sender / recipient name | `PII-1-NAME` |
| NIN / BVN | `PII-2-NIN`, `PII-2-BVN` |
| Email address | `PII-4-EMAIL` |
| Phone number(s) | `PII-3-PHONE` (libphonenumber-validated) |
| Bank account / SWIFT BIC | `PII-7-BANK-ACCOUNT`, `PII-7-SWIFT` |
| Address | `PII-1-ADDR` |
| Tax reference (RC number, TIN) | `PII-2-RC`, `PII-2-TIN` |

Each detection carries a `confidence` (1.0 for structurally validated IDs, lower for shape-only matches) and a statute citation drawn from the auto-loaded NDPA-2023.

---

## Sign the redacted output

When the invoice flows to a downstream processor, sign the redacted text so the recipient can verify provenance offline:

```python
from arche.sign import SignWorkflow, generate_keypair

issuer_key = generate_keypair()   # one-time per issuer
signed = SignWorkflow(jurisdiction="NG").sign(
    result.redacted_text,
    issuer_key,
    purpose="invoice_processing",
)
# `signed.serialize()` is a compact JWS string the consumer can verify
# with arche.sign.VerifyExtractWorkflow — no network call required.
```

---

## See also

- [Pipeline API reference](../api/resolve.md)
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
- [HOW-TO single-page walkthrough](https://github.com/unpatterned-labs/archeblob/main/HOW-TO.md)
