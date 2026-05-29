# Cookbook — Journalist PII scan on leaked documents

You're a journalist at a Lagos newsroom. A source leaked a 200-page PDF containing internal communications from a state-owned enterprise. Before publication you need to: (1) identify what PII the documents contain so you can responsibly redact what isn't in the public interest, (2) be able to show your legal team a reproducible audit of which categories you redacted and where, and (3) not accidentally store the raw PII in your own working notes, because if the source goes to court you don't want your laptop subpoenaed for the underlying NINs.

**Before arche-core:** you grep manually for digits-that-look-like-NINs, you eyeball addresses, you cross-reference IDs against published government databases (slow and ethically dicey), and your "what did we redact" notes are a Google Doc.

**With arche-core:** `from_url` or `Pipeline.process_file` reads the document; the detector emits categories + spans; the audit log records what was seen without ever storing the values.

```python
from arche import Pipeline
from arche.graph.audit import AuditLog

audit = AuditLog("./investigation_2026_06.sqlite")
pipeline = Pipeline(jurisdiction="NG")

for page_path in leaked_pages:
    result = pipeline.process_file(page_path)
    audit.emit_pipeline_result(result, document_id=page_path.name)
    print(f"\n=== {page_path.name} ===")
    for d in result.detections:
        print(f"  {d.category:25s} [{d.start:5d}:{d.end:5d}] page={d.metadata.get('page')}")
    save_redacted(page_path, result.redacted_text)
```

Output:

```
=== page_012.pdf ===
  PII-1-NAME                [  423:  441]    page=12
  PII-2-NIN                 [  502:  513]    page=12
  PII-3-PHONE               [  578:  595]    page=12
  PII-2-BVN                 [  611:  622]    page=12
  PII-4-ADDRESS             [  789:  834]    page=12
=== page_013.pdf ===
  PII-1-NAME                [   45:   62]    page=13
  PII-1-NAME                [  248:  271]    page=13
  PII-2-RC                  [  340:  348]    page=13
```

**Your laptop now holds:** the redacted PDFs (`[NIN]`, `[BVN]`, `[PHONE]` in place of the real values) and an audit SQLite. **It does not hold:** the actual NINs, BVNs, phone numbers, or addresses. If the laptop is seized, the originals stay safe in your encrypted source storage.

## Building the public-interest redaction list

Not every PII detection should be redacted in the final published version. The CEO's name is public; their personal phone isn't. arche emits all detections; you decide which to keep:

```python
KEEP_VISIBLE = {
    ("Adamu Bello", "PII-1-NAME"),     # Subject of the investigation
    ("Sterling Bank Limited", "PII-1-NAME"),  # Public entity
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
from arche.sign import generate_keypair

editor_key = generate_keypair()   # one-time, stored in the newsroom's wallet
legal_bundle = audit.export_signed(
    key=editor_key,
    purpose="newsroom_pre_publication_review",
)
# Hand legal_bundle to legal. They verify offline against editor_key.did_key.
```

## Honest caveats

- arche detects PII *categories*. It doesn't decide which detections are newsworthy and which aren't. That's a journalistic judgement; arche just shows you the full set.
- arche won't catch PII the detectors don't know about — internal employee IDs, custom membership numbers, sector-specific identifiers. For unusual identifier schemes that recur across the documents, you'd write a one-off custom recognizer (or just grep and review by hand for the long tail).
- The audit log proves *you redacted these categories on these dates*. It doesn't prove the *original* documents matched what you say they matched. For that, hash and timestamp the source materials separately before processing.

## See also

- [Cookbook — Web URL → Detection](web-to-detection.md) — when the leak comes via URL instead of file
- [Power-user cookbook: Civil-society audit](civil-society-audit.md) — when scanning a public dataset rather than a leaked document
- [Power-user: Citizen DSAR](../tutorials/citizen_dsar.md) — when the investigation requires filing a Data Subject Access Request
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md)