# How to extract entities from an invoice

Run a Nigerian business invoice (PDF) through the v0.2 `Pipeline` and get back redacted text + a typed list of detections + a signed audit trail. Total time: ~30 seconds end-to-end.

```bash
pip install arche-core[doc]   # adds docling for PDF/DOCX/PPTX/XLSX
```

```python
from collections import Counter
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")

result = pipeline.process_file("invoice.pdf")
print(Counter(d.category for d in result.detections))

print(result.redacted_text)   # Safe to share with downstream consumers
```

The counts depend on your invoice. Running the same two lines on the extracted text of a representative Nigerian invoice line - `"Invoice for Fatima Abdullahi, NIN 12345678901, phone 0803 555 7890, phone 0805 111 2222."` - gives:

```text
Counter({'PII-1-NAME': 2, 'PII-3-PHONE': 2, 'PII-2-NIN': 1})
```

Two things the older docs got wrong here: `Pipeline` takes no `audit_log=` argument (see the [constructor reference](../api/resolve.md#pipeline)), and `Result` has no `summary()` method - count over `result.detections` instead. To persist an audit trail to SQLite, see [Persisted audit log](../api/resolve.md#persisted-audit-log--signed-regulator-export).

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
# `signed` IS the compact JWS string - `SignWorkflow.sign()` returns `str`
# directly. There is no `.serialize()` call. The consumer verifies it with
# arche.sign.VerifyExtractWorkflow - no network call required.
print(signed[:40])
# eyJhbGciOiJFZERTQSIsImtpZCI6ImRpZDprZXk6
```

---

## See also

- [Pipeline API reference](../api/resolve.md)
- [Sign, share, extract tutorial](../tutorials/sign_share_extract.md)
