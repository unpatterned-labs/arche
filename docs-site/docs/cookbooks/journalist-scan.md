# Cookbook — Journalist PII scan on leaked documents

You're a journalist at a Lagos newsroom. A source leaked a 200-page PDF containing internal communications from a state-owned enterprise. Before publication you need to: (1) identify what PII the documents contain so you can responsibly redact what isn't in the public interest, (2) be able to show your legal team a reproducible audit of which categories you redacted and where, and (3) not accidentally store the raw PII in your own working notes, because if the source goes to court you don't want your laptop subpoenaed for the underlying NINs.

**Before arche-core:** you grep manually for digits-that-look-like-NINs, you eyeball addresses, you cross-reference IDs against published government databases (slow and ethically dicey), and your "what did we redact" notes are a Google Doc.

**With arche-core:** `Pipeline.process_file` parses the document via docling (PDF / DOCX / PPTX / XLSX); the detector emits categories + spans; the audit log records what was seen without ever storing the values.

```python
from arche import Pipeline
from arche.graph.audit import AuditEvent, AuditLog

audit = AuditLog("./investigation_2026_06.sqlite")
pipeline = Pipeline(jurisdiction="NG")


def record_result(audit: AuditLog, result, document_id: str) -> None:
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


for page_path in leaked_pages:
    result = pipeline.process_file(page_path)
    record_result(audit, result, document_id=page_path.name)
    print(f"\n=== {page_path.name} ===")
    for d in result.detections:
        print(f"  {d.category:25s} [{d.start:5d}:{d.end:5d}] {d.detector}")
    save_redacted(page_path, result.redacted_text)
```

Output (against a Nigerian intake-style page):

```
=== page_012.pdf ===
  PII-2-NIN                 [   46:   57] rule:ng_nin
  PII-2-BVN                 [   72:   83] rule:ng_bvn
  PII-3-PHONE               [   97:  110] phonenumbers:NG
  PII-4-ADDRESS             [  154:  195] rule:addr_parser
```

`Pipeline.process_file` needs the docling extra: `pip install arche-core[doc]` (or `[doc-ocr]` if your leak contains scanned PDFs). The character offsets index into the *parsed text*, not the original PDF coordinate space; if you need PDF-coordinate redaction, pass `result.redacted_text` to your downstream renderer or hand the original PDF to a redaction tool like `pikepdf` keyed on the detected `d.text` substring.

**Your laptop now holds:** the redacted PDFs (`[NIN]`, `[BVN]`, `[PHONE]` in place of the real values) and an audit SQLite. **It does not hold:** the actual NINs, BVNs, phone numbers, or addresses. If the laptop is seized, the originals stay safe in your encrypted source storage.

## Building the public-interest redaction list

Not every PII detection should be redacted in the final published version. The CEO's name is public; their personal phone isn't. arche emits all detections; you decide which to keep:

```python
# Illustrative — substitute names + entities from your own investigation.
KEEP_VISIBLE = {
    ("[Public Figure Name]", "PII-1-NAME"),   # Named individual whose role is public
    ("[Public Entity Name]", "PII-1-NAME"),   # Organisation the public is entitled to identify
}

def selective_redact(text: str, detections: list) -> str:
    out = text
    for d in sorted(detections, key=lambda x: -x.start):  # right-to-left so spans don't shift
        if (d.text, d.category) in KEEP_VISIBLE:
            continue
        out = out[:d.start] + f"[{d.category.split('-')[-1]}]" + out[d.end:]
    return out
```

You build the keep-visible list from the public-interest assessment; arche gives you the universe of detections to draw it from.

## What you have to show your legal team

When legal asks *"what did we publish?"* you have:

- The original encrypted source PDFs (in a separate vault).
- The redacted PDFs you actually published.
- The audit SQLite log, which shows every detection arche made.
- A signed export of the audit log proving the redaction wasn't tampered with after the fact:

```python
from datetime import datetime

from arche.sign import generate_keypair

editor_key = generate_keypair()   # one-time, stored in the newsroom's wallet
legal_bundle = audit.export_signed(
    key=editor_key,
    purpose="newsroom_pre_publication_review",
    since=datetime(2026, 6, 1),
    until=datetime(2026, 6, 30),
)
# Hand legal_bundle to legal. They verify offline against editor_key.did_key.
```

## Honest caveats

- arche detects PII *categories*. It doesn't decide which detections are newsworthy and which aren't. That's a journalistic judgement; arche just shows you the full set.
- arche won't catch PII the detectors don't know about — internal employee IDs, custom membership numbers, sector-specific identifiers. For unusual identifier schemes that recur across the documents, you'd write a one-off custom recognizer (or just grep and review by hand for the long tail).
- The audit log proves *you redacted these categories on these dates*. It doesn't prove the *original* documents matched what you say they matched. For that, hash and timestamp the source materials separately before processing.

---

_Verified against `arche-core` v0.2.0a3 on 2026-05-29 in a clean Python 3.11 venv (with `arche-core[doc]` for `process_file`). The `Pipeline.process_file` + `AuditEvent` + `export_signed` calls run as shown. `leaked_pages` and `save_redacted` are illustrative — substitute your own iteration over the source files._

## See also

- [Power-user cookbook: Civil-society audit](civil-society-audit.md) — when scanning a public dataset rather than a leaked document
- [Power-user: Citizen DSAR](../tutorials/citizen_dsar.md) — when the investigation requires filing a Data Subject Access Request
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md)
