"""Example 06 — Document ingest via docling + Pipeline + signing.

You're on Sterling Bank's operations team. Customers walk in, fill out paper intake forms, the branch scans them as PDFs, and the back office is supposed to redact PII before the scans land in your KYC review queue.

WITHOUT arche-core, the workflow is:

    1. The scanned PDF arrives in a shared drive.
    2. Operations runs OCR (Tesseract, Adobe, whatever's licensed).
    3. Someone hand-redacts the OCR output in Word with a marker tool.
    4. The redacted version goes into KYC review; the original is "supposed
       to be deleted" but actually sits on the shared drive for 90 days.
    5. The auditor wants to know how many PII items were redacted on doc 47
       of last March. Nobody can answer.

WITH arche-core[doc]:

    1. `Pipeline.process_file(path)` parses the PDF (via docling), runs the
       detectors, applies NDPA policy, and returns a Result with redacted
       text + audit entries.
    2. The original file path is in `result.metadata['source_file']` — you
       know what was processed.
    3. The audit log entry has every category + span — you can answer
       "how many PII items on doc 47" instantly.
    4. SignWorkflow wraps the redacted output in a JWS envelope so the KYC
       review team trusts the redaction came from the bank's pipeline,
       not from a hand-edited document someone could have tampered with.

This example creates a synthetic intake form, runs the full chain, and verifies the signed result on the receive side.

Requires the [doc] extra::

    pip install arche-core[doc]
    # For scanned PDFs / images:
    pip install arche-core[doc-ocr]

Run::

    python examples/06_doc_pipeline.py
"""

import tempfile
from pathlib import Path

from arche import Pipeline
from arche.doc import DOC_FEATURE_AVAILABLE, parse
from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair


def main() -> None:
    if not DOC_FEATURE_AVAILABLE:
        print("docling not installed — `pip install arche-core[doc]` first.")
        return

    # Create a synthetic Nigerian customer-intake markdown file. In production
    # this would be a scanned PDF or DOCX form coming out of the branch
    # scanner. The same Pipeline.process_file works on either.
    sample = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    sample.write(
        "# Sterling Bank — Customer Intake\n\n"
        "## Personal information\n\n"
        "- Full name: Adesola Okonkwo\n"
        "- NIN: 12345678901\n"
        "- BVN: 22156789012\n"
        "- Phone: +234 803 555 7890\n"
        "- Email: adesola@example.com\n\n"
        "## Address\n\n"
        "7B Allen Avenue, Ikeja, Lagos, Nigeria.\n"
    )
    sample.close()
    sample_path = Path(sample.name)

    # ---- Step 1: parse the document via docling ----------------------------
    parsed = parse(sample_path)
    print("=== arche.doc.parse() ===")
    print(f"  source:    {parsed.source}")
    print(f"  text:      {len(parsed.text)} chars")
    print(f"  num_pages: {parsed.num_pages}")
    print()

    # ---- Step 2: run the full pipeline -------------------------------------
    # process_file is the convenience shortcut: docling parse + Pipeline.process
    # in one call. result.metadata['source_file'] tells the auditor which file
    # this row belongs to.
    pipeline = Pipeline(jurisdiction="NG", tokenize_salt="sterling_2026")
    result = pipeline.process_file(sample_path)

    print("=== Pipeline.process_file ===")
    print(f"  detections found: {len(result.detections)}")
    for d in result.detections:
        print(f"    {d.category:25s} text={d.text!r}")
    print(f"  policy actions per NDPA-2023:")
    for o in result.policy_outcomes:
        print(f"    {o.category:25s} -> {o.action}")
    print(f"  redacted text (safe to ship to KYC review):")
    for line in result.redacted_text.splitlines():
        print(f"    {line}")
    print(f"  source file recorded: {result.metadata['source_file']}")
    print()

    # ---- Step 3: sign the result and verify offline ------------------------
    # The KYC review team receives the signed envelope and verifies offline.
    # They know the redaction came from the bank's pipeline (not from a hand-
    # edited document) because the signature binds the redacted text + the
    # policy outcomes + the source file hash + the statute version.
    bank_key = generate_keypair()
    signer = SignWorkflow(jurisdiction="NG", tokenize_salt="sterling_2026")
    signed = signer.sign(parsed.text, bank_key, purpose="intake_attestation")

    print("=== Sign + verify the document outcome ===")
    print(f"  signed envelope length: {len(signed)} chars")

    extracted = VerifyExtractWorkflow().process(signed)
    print(f"  recipient verification: {extracted.signature_valid}")
    print(f"  issuer:                 {extracted.issuer_did}")
    print(f"  jurisdiction:           {extracted.jurisdiction}")
    print(f"  statute:                {extracted.statute_at_signing}")

    sample_path.unlink(missing_ok=True)
    print("\nEnd-to-end document workflow complete. Now the auditor can answer")
    print("'what was redacted on intake doc X?' by looking at the audit log;")
    print("the KYC reviewer can answer 'is this redaction trustworthy?' by")
    print("verifying the signed envelope; and the source PDF stops sitting on")
    print("the shared drive because the signed envelope is the canonical")
    print("record from this point on.")


if __name__ == "__main__":
    main()
