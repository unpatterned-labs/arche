# Cookbook — Civil-society audit of a public dataset

You work for Paradigm Initiative in Lagos. The Nigerian Communications Commission published a CSV of "anonymised" customer complaints last month. You suspect the anonymisation isn't watertight — the published file might still contain detectable PII via name fields, partial NINs, addresses. You want to audit the file, file a notice with the NDPC if you find evidence of unlawful disclosure, and publish a reproducible report that other civil-society organisations can use as a template.

**Before arche-core:** you'd write per-pattern Python by hand, run it on the CSV, and your finding would be *"we found 27 instances we think are NINs."* The NCC denies. The NDPC investigation drags. Nobody can independently reproduce your scan.

**With arche-core:** the scan is one Pipeline call per row, the audit log shows exactly what the detector flagged, and the report you publish is reproducible by anyone with `pip install arche-core`.

```python
import csv
from arche import Pipeline
from arche.graph.audit import AuditLog

audit = AuditLog("./ncc_audit_2026_06.sqlite")
pipeline = Pipeline(jurisdiction="NG")

findings = []

with open("ncc_published_complaints_2026q1.csv") as f:
    for row_num, row in enumerate(csv.DictReader(f), start=1):
        # Concatenate the text fields the NCC labelled as "anonymised"
        text = " ".join([
            row["complaint_text"],
            row["resolution_notes"],
            row.get("customer_locality", ""),
        ])
        result = pipeline.process(text)
        audit.emit_pipeline_result(result, document_id=f"row_{row_num}")
        if result.detections:
            findings.append({
                "row_number": row_num,
                "categories_found": [d.category for d in result.detections],
                "high_tier_count": sum(
                    1 for d in result.detections
                    if d.sensitivity_tier.value == "high"
                ),
            })

print(f"Scanned {row_num} rows. PII detected in {len(findings)} of them.")
```

Counts are real, the audit log is reproducible, and you've stored zero actual PII on your laptop.

## What you can publish

The published report has three pieces:

1. **Aggregate finding.** *"Of 12,847 'anonymised' complaints in the NCC's published dataset, 1,094 (8.5%) contain at least one HIGH-tier PII item under NDPA-2023 s.30. The most common categories were PII-1-NAME (719), PII-3-PHONE (412), and PII-2-NIN (87)."*

2. **Reproducibility appendix.** *"This audit was conducted using arche-core v0.2.0a3 with NDPA-2023 statute YAML at version 1.0. To reproduce: `pip install arche-core==0.2.0a3` and run the script in Appendix B against the public file linked in footnote 4."*

3. **Signed audit log bundle.** *"The signed audit log is available at [link]. The NDPC can verify offline against Paradigm Initiative's did:key (footnote 5) that the detection set has not been altered since the date of publication."*

```python
from arche.sign import generate_keypair

paradigm_key = generate_keypair()   # stored in the organisation's wallet
audit_bundle = audit.export_signed(
    key=paradigm_key,
    purpose="ncc_audit_public_report_2026q2",
)
with open("paradigm_ncc_audit.jws", "w") as f:
    f.write(audit_bundle)
```

The published bundle proves what was detected. It contains no PII values — only category counts, span offsets, and document (row) identifiers.

## What you file with the NDPC

The complaint to the NDPC under NDPA-2023 s.36 cites the same audit bundle. You don't have to share the raw NCC file with the NDPC — the NCC already has it. You share evidence that *anyone running arche-core on the file would find the same 1,094 records with HIGH-tier PII.*

## Building a template for other civil-society orgs

Once your script works for the NCC dataset, the same pattern works for any other public dataset claiming to be anonymised. The Kenya Open Data portal. The South African Department of Health public extracts. The Ghanaian electoral roll. Change the `jurisdiction=` parameter and the statute YAML changes; the rest of the workflow is identical. Publish the script as a template. Other organisations adopt the same pattern. The collective pressure on public-sector data stewards to anonymise correctly compounds.

## Honest caveats

- arche detects what the African-context layer knows about. A novel identifier (a custom membership number for a specific welfare program, for example) won't be caught unless someone writes a recognizer for it. Treat the scan as a *floor* of PII presence, not a ceiling.
- arche's detection set is auditable but not omniscient. The audit shows *what arche-core found*, not *all possible PII in the file*. Be honest in the report about the difference.
- The NDPC may push back on whether the NCC's anonymisation actually violates NDPA. Your job is to surface the evidence; the legal interpretation is theirs (and the courts').

## See also

- [Cookbook — Journalist PII scan](journalist-scan.md) — same detection toolkit, different ethical frame
- [Power-user: Citizen DSAR](../tutorials/citizen_dsar.md) — the individual-rights version of this workflow
- [Pan-African PII Taxonomy v0.1](https://github.com/unpatterned-labs/arche/tree/main/datasets/pan-african-pii-taxonomy) — the taxonomy your report cites
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md)
