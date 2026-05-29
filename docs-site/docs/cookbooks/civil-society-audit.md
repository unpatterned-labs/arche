# Cookbook — Civil-society audit of a public dataset

You work for a Lagos-based civil-society organisation working on data rights — call it Paradigm Initiative, Yiaga Africa, or your own org. The Federal Ministry of Health publishes the [Nigeria Health Facility Registry (HFR)](https://hfr.health.gov.ng/) as open data — a master list of every public and private health facility in Nigeria, mirrored on the [Humanitarian Data Exchange](https://data.humdata.org/dataset/nigeria-health-facilities) under a permissive licence. You want to audit the published file to confirm the anonymisation is sound — specifically whether any "facility contact" columns inadvertently leak the personal mobile numbers of named facility managers rather than carrying institutional landlines.

You want three things from the audit: (1) a reproducible scan that anyone can re-run, (2) a count of how many rows contain detectable PII categories under NDPA-2023, and (3) a signed bundle proving what the scan found so the NDPC can act on it if anything turns up.

**Before arche-core:** you'd write per-pattern Python by hand, eyeball the CSV in Excel, and your finding would be *"we found 27 instances we think are NINs."* The Federal Ministry denies. Nobody can independently reproduce your scan.

**With arche-core:** the scan is one `Pipeline.process()` call per row, the audit log shows exactly what the detector flagged, and the report you publish is reproducible by anyone with `pip install arche-core`.

## Step 1: download the public dataset

The Nigeria HFR ships as a CSV mirrored on HDX. Download it once:

```bash
curl -L -o nigeria_hfr.csv \
    "https://data.humdata.org/dataset/nigeria-health-facilities/resource/4658aa59-0554-4fac-8473-377da4b7a0e9/download/nigeriahealthfacilities.csv"
```

(If the HDX resource has been rotated, browse [data.humdata.org/dataset/nigeria-health-facilities](https://data.humdata.org/dataset/nigeria-health-facilities) and grab the current CSV link. The official source is [hfr.health.gov.ng](https://hfr.health.gov.ng/); HDX is a stable mirror.)

You now have a CSV on disk. The columns are whatever the Federal Ministry chose to publish — facility names, addresses, ownership, ward/LGA/state, and a contact column or two. The script below makes no assumption about which columns are which; it concatenates every string field per row and lets `Pipeline` decide.

## Step 2: run the scan

```python
import csv

from arche import Pipeline
from arche.graph.audit import AuditEvent, AuditLog

audit = AuditLog("./hfr_audit.sqlite")    # output file — created on first emit
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


findings = []

with open("nigeria_hfr.csv", encoding="utf-8") as f:
    for row_num, row in enumerate(csv.DictReader(f), start=1):
        # Concatenate every string field in the row. No assumption about
        # which columns are which — works against any CSV the registry
        # decides to publish next quarter.
        text = " ".join(str(v) for v in row.values() if v)
        result = pipeline.process(text)
        record_result(audit, result, document_id=f"row_{row_num}")
        if result.detections:
            findings.append({
                "row_number": row_num,
                "categories_found": sorted({d.category for d in result.detections}),
                "high_tier_count": sum(
                    1 for d in result.detections
                    if d.sensitivity_tier.value == "high"
                ),
            })

print(f"Scanned {row_num} rows. PII detected in {len(findings)} of them.")
```

The two file paths in the script:

- **`./hfr_audit.sqlite`** — **output**. `AuditLog(path)` creates this SQLite file on the first `emit()` call. You can name it whatever; nothing in arche-core depends on the name.
- **`nigeria_hfr.csv`** — **input**. The file you downloaded in step 1. The encoding hint (`utf-8`) matters because the HFR mixes ASCII facility names with accented Yoruba / Hausa place names.

## Step 3: read the findings honestly

Most rows in a professionally-curated registry like the HFR will return zero detections. That's a useful outcome on its own — it lets you publish *"we audited the published HFR with arche-core v0.2.0a3 and found ≤N rows containing detectable PII categories under NDPA-2023; the Federal Ministry's anonymisation appears sound."* A clean audit is publishable evidence too.

Where detections fire, they cluster in a few predictable places:

- **`PII-4-LOCATION` and `PII-4-ADDRESS`** — the registry intentionally publishes addresses (that's the point of a facility registry). These are not PII-violations; institutional addresses are public-record data under NDPA-2023 s.31 (legitimate interests). Filter these out of the findings count before drawing conclusions.
- **`PII-3-PHONE`** — the cases worth investigating. If the contact column contains a Nigerian mobile number (`+234 80x...`, `+234 81x...`, `+234 70x...`) rather than a landline (`+234 1 ...`, `+234 9 ...`), it may be a personal handset rather than a switchboard. Flag for follow-up.
- **`PII-1-NAME`** — names appearing in facility descriptions or notes columns. A facility called *"Dr Mike Adenuga Memorial Clinic"* names a public figure (no concern); a "facility manager: Adesola Okonkwo, +2348012345678" line is a different matter.

The audit log is the ground truth — the high-tier filter in the script gives you the rows worth a human look:

```python
high_tier_rows = [f for f in findings if f["high_tier_count"] > 0]
print(f"Rows with HIGH-tier PII (worth a human review): {len(high_tier_rows)}")
```

## Step 4: publish the report

The published report has three pieces:

1. **Aggregate finding.** *"Of N rows in the published Nigeria HFR (vintage: <date>), M rows contain at least one PII category at HIGH sensitivity tier under NDPA-2023. After filtering out institutional addresses (public-record under NDPA-2023 s.31), K rows remain that may warrant human review."* If `K = 0` say so plainly; that's the finding.

2. **Reproducibility appendix.** *"This audit was conducted using arche-core v0.2.0a3 with NDPA-2023 statute YAML at version 1.0. To reproduce: `pip install arche-core==0.2.0a3`, download the HFR CSV from [data.humdata.org/dataset/nigeria-health-facilities](https://data.humdata.org/dataset/nigeria-health-facilities), and run the script in Appendix B against it."*

3. **Signed audit log bundle** for cryptographic non-repudiation of the scan:

```python
from datetime import datetime
from arche.sign import generate_keypair

paradigm_key = generate_keypair()       # in production, load from your org's wallet
audit_bundle = audit.export_signed(
    key=paradigm_key,
    purpose="hfr_audit_public_report_2026q2",
    since=datetime(2026, 4, 1),
    until=datetime(2026, 6, 30),
)
with open("paradigm_hfr_audit.jws", "w", encoding="utf-8") as f:
    f.write(audit_bundle)
```

The published bundle proves what was detected. It contains no PII values — only category counts, span offsets, row identifiers, and the statute references.

## What you file with the NDPC (only if you actually found something)

If the audit surfaces material findings — personal mobile numbers in contact columns, named individuals whose role doesn't justify being on the registry — the complaint to the NDPC under NDPA-2023 s.36 cites the same audit bundle. You don't have to share the raw HFR file with the NDPC; the Federal Ministry already published it. You share evidence that *anyone running arche-core on the file would find the same K records with HIGH-tier PII.*

If the audit comes back clean, publish the clean finding. *"We checked, here's the method, here's the bundle, the published HFR appears compliant with NDPA-2023 s.30."* This is also useful work — it builds trust in the dataset and demonstrates the audit method.

## Building a template for other civil-society orgs

Once your script works for the HFR, the same pattern works for any other published African dataset. Swap the file path, swap the `jurisdiction=` parameter to match the relevant statute, re-run. Candidate next targets:

- **Kenya Health Facility Registry** under `jurisdiction="KE"` (Kenya DPA).
- **South African National Health Facility Information System** (where it's published in open form) under `jurisdiction="ZA"` (POPIA).
- **Ghana Health Service facility registry** under `jurisdiction="GH"` (Ghana DPA).
- Any government open-data portal CSV in the four launch jurisdictions where the dataset purports to be anonymised or institutional-only.

Publish the script as a template. Other organisations adopt the same pattern. The collective pressure on public-sector data stewards to anonymise correctly compounds.

## Honest caveats

- arche detects what the African-context layer knows about. A novel identifier (a custom Federal Ministry internal staff ID, for example) won't be caught unless someone writes a recognizer for it. Treat the scan as a *floor* of PII presence, not a ceiling.
- The HFR was already curated by eHealth Africa and the Federal Ministry. A clean audit doesn't mean *"we vetted the dataset for all possible PII;"* it means *"we ran arche-core against it and these are the categories it found."* Be honest in the report about the difference.
- Phone numbers in the registry that look like personal mobiles may legitimately be: an institutional WhatsApp number, a facility manager's published direct line (consented), a switchboard that happens to be mobile-formatted. Flag for human review; do not name an individual as having had their PII leaked without manual verification.
- The NDPC may push back on the threshold for *"detectable PII = unlawful disclosure."* Your job is to surface the evidence; the legal interpretation is theirs (and the courts').

---

_Verified against `arche-core` v0.2.0a3 on 2026-05-29 in a clean Python 3.11 venv. The `Pipeline.process` loop, `AuditEvent`-based audit emission, `sensitivity_tier.value` filter, and `export_signed` calls run as shown. The Nigeria Health Facility Registry CSV is real and downloadable from [hfr.health.gov.ng](https://hfr.health.gov.ng/) (official) or [data.humdata.org/dataset/nigeria-health-facilities](https://data.humdata.org/dataset/nigeria-health-facilities) (HDX mirror). The HDX resource ID rotates from time to time; if the `curl` link in step 1 returns 404, browse the dataset page and copy the current CSV URL._

## See also

- [Cookbook — Journalist PII scan](journalist-scan.md) — same detection toolkit, different ethical frame
- [Power-user: Citizen DSAR](../tutorials/citizen_dsar.md) — the individual-rights version of this workflow
- [Pan-African PII Taxonomy v0.1](https://github.com/unpatterned-labs/arche/tree/main/datasets/pan-african-pii-taxonomy) — the taxonomy your report cites
- [Why arche & when to use it](../tutorials/arche_vs_alternatives.md)
- [Roadmap](../concepts/roadmap.md)

Sources:
- [Nigeria Health Facility Registry — official portal](https://hfr.health.gov.ng/)
- [Nigeria Health Facilities — Humanitarian Data Exchange (HDX)](https://data.humdata.org/dataset/nigeria-health-facilities)
- [National Health Facility Registry — NCDC Data Portal](https://dataportal.ncdc.gov.ng/dataset/national-health-facility-registry)
