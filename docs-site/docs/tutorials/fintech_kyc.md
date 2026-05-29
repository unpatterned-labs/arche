# Tutorial: Fintech KYC -- Document Processing and Compliance

**Audience**: Fintech backend engineers, compliance teams, procurement officers
**Time**: 10-15 minutes
**Prerequisites**: Python 3.10+, `pip install arche-core`

---

## The Problem

A Nigerian fintech processes customer documents for KYC (Know Your Customer) compliance: utility bills, ID cards, and bank statements. They need to:

1. Extract customer identity from unstructured document text
2. Validate national ID numbers (NIN, BVN) with checksums
3. Check for PII compliance under Nigeria's NDPA
4. Match extracted identities against existing CRM records
5. Produce audit-safe logs with no PII

arche handles this entire pipeline.

## Install

```bash
pip install arche-core          # regex backend (no ML, works offline)
# or
pip install arche-core[all]     # full stack with GliNER + Presidio
```

## Step 1: Create Synthetic Document Text

```python
# Synthetic Nigerian fintech documents -- all data is fictitious

utility_bill = """
EKEDC ELECTRICITY BILL
Customer: Oluwaseun Adeyemi
Account No: 0145-2367-8901
Address: 14 Allen Avenue, Ikeja, Lagos
Phone: +234 803 456 7890
Amount Due: NGN 45,750.00
Bill Date: 2026-03-15
NIN on file: 12345678901
"""

bank_statement = """
GUARANTY TRUST BANK - MONTHLY STATEMENT
Account Holder: O.S. Adeyemi
Account Number: 0123456789
BVN: 22198765432
Period: March 2026
Opening Balance: NGN 1,250,000.00
Closing Balance: NGN 980,430.50
Contact: adeyemi.seun@email.com
Phone: 08034567890
Branch: Ikeja, Lagos
"""

id_card_text = """
FEDERAL REPUBLIC OF NIGERIA
NATIONAL IDENTITY CARD
Name: ADEYEMI, OLUWASEUN BABATUNDE
NIN: 12345678901
Date of Birth: 15/06/1990
Gender: Male
Address: 14 Allen Avenue, Ikeja, Lagos State
Issue Date: 20/01/2022
"""

# A CRM record for comparison
crm_record = {
    "name": "Oluwaseun B. Adeyemi",
    "phone": "+2348034567890",
    "national_id": "12345678901",
    "email": "adeyemi.seun@email.com",
    "address": "14 Allen Ave, Ikeja, Lagos",
}
```

## Step 2: Extract Entities from Documents

```python
from arche import detect

# Process each document
print("=== Utility Bill ===\n")
bill_entities = detect(utility_bill, backend="regex")
for e in bill_entities:
    print(f"  {e.entity_type}: {e.text}")
    if e.metadata:
        # Show validation metadata
        relevant = {k: v for k, v in e.metadata.items()
                    if k in ("country", "id_type", "operator", "e164")}
        if relevant:
            print(f"    metadata: {relevant}")
print()

print("=== Bank Statement ===\n")
stmt_entities = detect(bank_statement, backend="regex")
for e in stmt_entities:
    print(f"  {e.entity_type}: {e.text}")
    if e.metadata:
        relevant = {k: v for k, v in e.metadata.items()
                    if k in ("country", "id_type", "operator", "e164")}
        if relevant:
            print(f"    metadata: {relevant}")
print()

print("=== ID Card ===\n")
id_entities = detect(id_card_text, backend="regex")
for e in id_entities:
    print(f"  {e.entity_type}: {e.text}")
    if e.metadata:
        relevant = {k: v for k, v in e.metadata.items()
                    if k in ("country", "id_type")}
        if relevant:
            print(f"    metadata: {relevant}")
```

Key things arche does here:
- **NIN "12345678901"** is detected as NATIONAL_ID (not phone) with format validation
- **BVN "22198765432"** is detected as NATIONAL_ID with the 22-prefix BVN pattern
- **Phone "+234 803 456 7890"** is normalized to E.164 format with operator detection
- **NGN 45,750.00** is detected as MONEY with Nigerian Naira currency

## Step 3: Match Against CRM Records

```python
from arche import match

# Extract identity from the utility bill for matching
doc_identity = {
    "name": "Oluwaseun Adeyemi",
    "phone": "+234 803 456 7890",
    "national_id": "12345678901",
}

# Compare against CRM record using Fellegi-Sunter
score = match(doc_identity, crm_record, jurisdiction="NG")

print("=== CRM Record Matching ===\n")
print(f"Document: {doc_identity['name']}")
print(f"CRM:      {crm_record['name']}")
print()
print(f"Score:       {score.score:.4f}")
print(f"Decision:    {score.decision}")
print(f"Factors:     {score.factors}")
print(f"Explanation: {score.explanation}")
print()

# The NIN match is the strongest signal
if score.factors.get("national_id", 0) >= 0.99:
    print("National ID match confirms identity -- highest confidence signal.")
if score.factors.get("phone", 0) >= 0.99:
    print("Phone number match after normalization (+234 prefix = 0 prefix).")
if score.factors.get("name", 0) >= 0.80:
    print("Name match: 'Oluwaseun Adeyemi' ~ 'Oluwaseun B. Adeyemi'")
```

Notice that arche normalizes "+234 803 456 7890" and "08034567890" to the same number (stripping country code vs local prefix).

## Step 4: Full Pipeline with Statute-Aware Policy

The `Pipeline` primitive composes detection + statute policy + audit in one call. Point it at a jurisdiction and every detection is tied to the law that governs it and the action that law requires.

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")    # auto-loads NDPA-2023
result = pipeline.process(utility_bill)

print("=== Detections (PII tier + statute citation) ===")
for d in result.detections:
    print(f"  {d.category:14} tier={d.sensitivity_tier.value:9} {d.regulatory_citation}")
# PII-2-NIN      tier=high      NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME     tier=moderate  NDPA-2023 s.30          (x2 - given + family name)
# PII-4-LOCATION tier=low       NDPA-2023 s.31 (legitimate interests)
# PII-4-ADDRESS  tier=moderate  NDPA-2023 s.30
# PII-3-PHONE    tier=moderate  NDPA-2023 s.30

print("\n=== Policy outcomes (what NDPA-2023 requires) ===")
for o in result.policy_outcomes:
    print(f"  {o.category:14} {o.action:10} {o.statute_reference}")
# PII-2-NIN      mask       NDPA-2023 s.30, NIMC Act s.27
# PII-1-NAME     tokenize   NDPA-2023 s.30
# PII-4-LOCATION retain     NDPA-2023 s.31 (legitimate interests)
# PII-4-ADDRESS  generalize NDPA-2023 s.30
# PII-3-PHONE    tokenize   NDPA-2023 s.30

print("\n=== Redacted text (safe to store or share) ===")
print(result.redacted_text)
```

Different categories get different statutory treatment automatically: the NIN is **masked**, the name and phone number are **tokenized** (so you can still link records across documents), the city is **retained** under legitimate-interest, and the street address is **generalized**. Four of arche's six policy actions, all driven by one statute YAML file — no hand-written rules.

## Step 5: Audit-Safe Logging

This is critical for compliance. You need to log what happened without storing PII. The `Pipeline` gives you two PII-free artifacts: the **redacted text** and the **audit log**.

```python
import json

# 1. The redacted text has no raw PII -- safe to store, log, or send downstream
print("=== Redacted text ===")
print(result.redacted_text)
# ... Customer: NAME_6212d138 NAME_ac9232cc ... NIN on file: [NIN] ...

# 2. The audit log records WHAT was found and WHY -- never the PII values themselves
print("\n=== Audit events (first 2) ===")
for event in result.audit_log[:2]:
    print(json.dumps(event, default=str, indent=2))
# {
#   "event_type": "detection",
#   "category": "PII-2-NIN",
#   "span": [204, 215],
#   "detector": "rule:ng_nin",
#   "sensitivity_tier": "high",
#   "regulatory_citation": "NDPA-2023 s.30, NIMC Act s.27"
# }
```

Each audit event stores the **category label**, **character span**, **detector**, and **statute citation** — but never the NIN, name, or phone value itself. You can ship this straight to your logging pipeline and stay compliant: an auditor can reconstruct exactly what was detected and which law applied, with zero PII at rest. (Set `Pipeline(audit=False)` to skip audit-log emission.)
```

## Step 6: Batch Processing

For production fintech pipelines processing many documents, reuse one `Pipeline` (it loads the statute once) and call `process()` per document:

```python
from arche import Pipeline

# Configure once for Nigerian fintech documents -- the NDPA-2023 statute
# is loaded a single time and reused across the batch.
pipeline = Pipeline(jurisdiction="NG")

documents = [utility_bill, bank_statement, id_card_text]
results = [pipeline.process(doc) for doc in documents]

print("=== Batch Processing Results ===\n")
for i, result in enumerate(results, start=1):
    print(f"Document {i}:")
    print(f"  Detections:      {len(result.detections)}")
    print(f"  Policy outcomes: {len(result.policy_outcomes)}")
    print(f"  Redacted: {result.redacted_text.strip()[:80]}...")
    print()
```

For files (PDF/DOCX) rather than strings, use `pipeline.process_file(path)` with the `arche-core[pdf]` / `[docx]` extras installed.

## Step 7: ISBN Detection (Bonus)

For fintechs processing invoices that include book orders:

```python
from arche import detect, match

# A bookstore invoice
invoice = """
TERRA KULTURE BOOKSTORE - INVOICE
Customer: Chimamanda Obi
Order #: TK-2026-0891

Items:
1. ISBN 978-0-13-468599-1 "Clean Code" x 2 @ NGN 15,000.00
2. ISBN 0-321-12521-5 "Domain-Driven Design" x 1 @ NGN 22,500.00

Subtotal: NGN 52,500.00
Delivery to: Victoria Island, Lagos
"""

# Detect ISBNs with checksum validation
entities = detect(invoice, backend="regex")
print("=== Detected Entities ===\n")
for e in entities:
    print(f"  [{e.entity_type}] {e.text}")
    if e.entity_type == "ISBN" and e.metadata:
        print(f"    ISBN type: {e.metadata.get('isbn_type', 'unknown')}")
        print(f"    Valid checksum: {e.metadata.get('checksum_valid', 'unknown')}")
print()

# Match ISBNs across formats (ISBN-10 and ISBN-13 of the same book)
score = match("0-321-12521-5", "978-0-321-12521-7", entity_type="isbn")
print(f"ISBN cross-format match: {score}")
print(f"  ISBN-10 and ISBN-13 of the same book are recognized as identical")
print()

# For book metadata (title, authors, publisher), call the Open Library API
# directly, or use the `arche-live` package. ISBN *metadata enrichment* was
# removed from arche-core in v0.2.0a2 to keep the core detection-focused.
```

## Step 8: Compare -- arche vs Raw LLM Extraction

What happens if you use an LLM to extract identities from these documents?

```python
# === What an LLM gives you ===
# (Conceptual -- using OpenAI as example)
#
# response = openai.chat.completions.create(
#     model="gpt-4",
#     messages=[{
#         "role": "user",
#         "content": f"Extract all identity information from this text:\n{utility_bill}"
#     }]
# )
#
# Problems with LLM extraction:
#
# 1. HALLUCINATED DIGITS: LLM might return NIN "1234567890" (10 digits)
#    instead of "12345678901" (11 digits). arche validates the checksum.
#
# 2. NO VALIDATION: LLM cannot verify that a BVN starts with "22" or
#    that a NIN is exactly 11 digits. arche has format validators for
#    50+ African ID types.
#
# 3. REQUIRES API KEY + INTERNET: LLM calls fail in air-gapped
#    government data centers. arche works offline.
#
# 4. COST: Processing 10,000 documents through GPT-4 costs ~$50-100.
#    arche processes them for free on CPU.
#
# 5. NO MATCHING: LLM extracts entities but cannot match
#    "Oluwaseun Adeyemi" against "O.S. Adeyemi" with probabilistic
#    confidence. arche does this with Fellegi-Sunter.
#
# 6. NO COMPLIANCE: LLM doesn't know that a NIN is "sensitive" under
#    NDPA or that a BVN requires consent for storage. arche classifies
#    PII by jurisdiction.

# === arche advantage ===
# arche's deterministic validators (checksum, prefix, length) catch what
# a model hallucinates. Install the optional GLiNER neural layer
# (`pip install arche-core[detect]`) for multilingual soft-PII, and the
# Pipeline still checksums, format-validates, and statute-classifies every
# neural suggestion. Best of both worlds.
```

## What You Learned

1. **`detect()`** extracts and validates entities from unstructured documents -- NIN checksum, BVN prefix, phone normalization, currency detection
2. **`match()`** with dict inputs does full Fellegi-Sunter comparison across name, phone, NID, email, and address fields
3. **`Pipeline.process()`** runs detection + statute policy + audit in one call, returning detections (with sensitivity tier + statute citation), policy outcomes, and redacted text
4. **`result.redacted_text`** and **`result.audit_log`** give audit-safe output (category labels + spans + citations, no PII values) -- critical for NDPA compliance
5. **One `Pipeline`, looped over `process()`** (or `process_file()`) handles batch workloads -- the statute loads once
6. **ISBN detection** with checksum validation and cross-format matching (ISBN-10 to ISBN-13)
7. **LLMs hallucinate digits**; arche validates them with deterministic checksums and statute-grounded policy.

## Next Steps

- Work through [Entity Resolution](entity_resolution.md) to link records across multiple documents
- See the [arche vs Alternatives](arche_vs_alternatives.md) comparison guide
- Try [Sign, Share, Extract](sign_share_extract.md) for verifiable, signed redaction envelopes

---

*All data in this tutorial is synthetic. No real customer documents, NINs, BVNs, or financial data were used.*
