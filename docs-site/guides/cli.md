# CLI Reference

> **arche-core v0.2.0a3 does not ship a CLI.** The Python API is the entry point for every workflow. A v0.2-aware CLI is on the roadmap, not committed; the work is gated on the same beta criteria as the rest of v0.3.

The Python API takes three lines:

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process("NIN 12345678901, BVN 22156789012.")
print(result.redacted_text)
```

If you need command-line ergonomics today, drop a small Python script in your repo and run it under `uv run` or `python -m`. Examples below.

---

## Workflow scripting today

For batch processing — reading multiple files, writing redacted outputs alongside them, populating an audit log — a short script does what a CLI would:

```python
# bin/redact_intake.py
import sys
from pathlib import Path
from arche import Pipeline
from arche.graph.audit import AuditLog

audit = AuditLog("./compliance.sqlite")
pipeline = Pipeline(jurisdiction="NG", audit_log=audit)

for raw in sys.argv[1:]:
    path = Path(raw)
    text = path.read_text(encoding="utf-8")
    result = pipeline.process(text)
    out = path.with_suffix(path.suffix + ".redacted")
    out.write_text(result.redacted_text, encoding="utf-8")
    print(f"{path.name}: {len(result.detections)} detections -> {out.name}")
```

Run it:

```bash
uv run python bin/redact_intake.py inputs/*.txt
```

The audit log captures every detection and policy decision across the batch. For a signed regulator export afterwards, see the [Audit log example](https://github.com/unpatterned-labs/arche/blob/main/examples/05_audit_log.py).

---

## Document ingest (PDF / DOCX / PPTX / XLSX)

Install the optional extra and use `Pipeline.process_file(path)`:

```bash
pip install arche-core[doc]
```

```python
from arche import Pipeline

pipeline = Pipeline(jurisdiction="NG")
result = pipeline.process_file("intake.pdf")
print(result.redacted_text)
```

`result.metadata["source_file"]` records which file produced the row — useful when an auditor asks *"which document did this detection come from?"*. Worked end-to-end example: [`examples/06_doc_pipeline.py`](https://github.com/unpatterned-labs/arche/blob/main/examples/06_doc_pipeline.py).

---

## URL ingest

For public URLs, `arche.ingest.from_url` is the SSRF-guarded fetch helper:

```python
from arche import Pipeline
from arche.ingest import from_url

text = from_url("https://businessday.ng/news/some-article/")
result = Pipeline(jurisdiction="NG").process(text)
```

See the [Web URL → Detection cookbook](../cookbooks/web-to-detection.md) for the full walkthrough and the security boundary that `from_url` does and does not provide.

---

## When the CLI returns

A v0.2-aware CLI is on the roadmap (not committed for v0.3 beta) with the rough shape:

```bash
arche pipeline --jurisdiction NG "NIN 12345678901"
arche sign document.txt --key issuer.jwk --purpose dsar_response
arche verify signed-document.jws
arche dsar --jurisdiction NG --target "Bank XYZ" --subject "Adesola Okonkwo"
arche audit query --since 2026-01-01 --statute NDPA-2023
arche audit export --key compliance.jwk --purpose ndpc_audit
```

If you'd find a CLI useful for your workflow, open an issue tagged `cli` on [github.com/unpatterned-labs/arche](https://github.com/unpatterned-labs/arche/issues) — the prioritisation conversation is public.
