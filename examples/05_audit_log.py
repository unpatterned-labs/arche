"""Example 05 — SQLite audit log + signed regulator export.

You're the compliance officer at Sterling Bank. The NDPC published a circular last month requiring quarterly audit handoffs for every regulated processor of personal data. The deadline is in three weeks. The auditor wants to see, for the last 90 days, every PII detection your data pipeline made, every redaction action applied, and proof you never stored the underlying values.

WITHOUT arche-core, the typical setup looks like this:

    1. Your ML team built a redaction pipeline last year. It writes detections
       to the data warehouse so the analytics team can see them. The auditor
       wants to know whether any of those rows accidentally include raw PII.
       You spend a week running SQL spelunking against the warehouse to find out.
    2. The pipeline logs to CloudWatch or Loki. Logs are 90-day rolling and
       partially in the wrong format. You write a Python script to scrape them
       into a CSV the auditor can read.
    3. You write a 12-page Word doc summary citing NDPA §30 and §34. The
       auditor's office can't independently verify the numbers — they take
       your word for it, or they spend a week of their own time replaying
       your pipeline.
    4. Next quarter you do it all again.

WITH arche-core, the audit log IS the deliverable:

    1. Every Pipeline run emits append-only audit events automatically.
       PII values are never stored — only category labels, character spans,
       SHA-256 document hashes. The schema is regulator-readable by design
       (PRD §8.2).
    2. `audit.compliance_report_markdown()` produces the report the auditor
       wants, with citations attached to every redaction action.
    3. `audit.export_signed()` wraps the report in a JWS envelope signed
       with the compliance officer's did:key. The NDPC verifies offline —
       no need to take your word for it.

This example simulates a small batch of detections and policy decisions and walks through the three regulator-facing surfaces: live query, markdown report, signed export.

Run::

    python examples/05_audit_log.py
"""

from arche.graph.audit import AuditEvent, AuditLog
from arche.sign import VerifyExtractWorkflow, generate_keypair

# ─────────────────────────────────────────────────────────────────────────
# Set up an audit log. In-memory for the demo; in production this is a file
# path (e.g. /var/lib/sterling/compliance.sqlite) that survives restarts.
# ─────────────────────────────────────────────────────────────────────────

audit = AuditLog(":memory:")

# Simulate Pipeline emissions for several customer documents.
# Notice none of these tuples contains a PII VALUE — only category, span,
# and confidence. That's the regulator-safety guarantee, baked in at the
# schema level.
detections = [
    ("doc_001", "PII-2-NIN",   (30, 41), 0.95, "rule:ng_nin"),
    ("doc_001", "PII-2-BVN",   (79, 90), 0.85, "rule:ng_bvn"),
    ("doc_002", "PII-2-NIN",   (10, 21), 0.92, "rule:ng_nin"),
    ("doc_002", "PII-3-PHONE", (50, 67), 0.99, "phonenumbers:NG"),
    ("doc_003", "PII-2-GHANA_CARD", (5, 22), 0.98, "rule:gh_card"),
]

for doc_hash, category, span, conf, detector in detections:
    audit.emit(AuditEvent.detection(
        document_hash=doc_hash,
        category=category,
        span=span,
        confidence=conf,
        detector=detector,
    ))

# Now record the policy decisions the engine made. Notice each one carries
# the statute reference. This is the column the auditor cares about: when
# you redacted that NIN, which rule fired and where is it documented?
policy_decisions = [
    ("doc_001", "PII-2-NIN", "mask",     "NDPA-2023", "NDPA-2023 s.30, NIMC Act s.27"),
    ("doc_001", "PII-2-BVN", "mask",     "NDPA-2023", "NDPA-2023 s.30, CBN BVN policy 2014"),
    ("doc_002", "PII-2-NIN", "mask",     "NDPA-2023", "NDPA-2023 s.30, NIMC Act s.27"),
    ("doc_002", "PII-3-PHONE", "tokenize", "NDPA-2023", "NDPA-2023 s.30"),
    ("doc_003", "PII-2-GHANA_CARD", "mask", "GHANA-DPA", "Ghana DPA s.20, NIA Act"),
]

for doc_hash, category, action, statute_id, ref in policy_decisions:
    audit.emit(AuditEvent.policy(
        document_hash=doc_hash,
        category=category,
        action=action,
        statute_id=statute_id,
        statute_reference=ref,
    ))

print(f"Audit log size: {audit.count()} events")
print(f"  detections:    {audit.count(event_type='detection')}")
print(f"  policies:      {audit.count(event_type='policy')}")
print()

# ─────────────────────────────────────────────────────────────────────────
# Query the log (regulator-style: show everything that touched a document)
# ─────────────────────────────────────────────────────────────────────────

print("=== Events for doc_001 ===")
for evt in audit.query(document_hash="doc_001"):
    if evt.event_type == "detection":
        print(f"  [DETECT] {evt.category:25s} span={evt.span_start}:{evt.span_end} "
              f"conf={evt.confidence:.2f} by {evt.detector}")
    else:
        print(f"  [POLICY] {evt.category:25s} -> {evt.action:10s} "
              f"({evt.statute_reference[:50]})")

# ─────────────────────────────────────────────────────────────────────────
# Compliance report (markdown — what the auditor actually reads)
# ─────────────────────────────────────────────────────────────────────────

print("\n=== Markdown compliance report ===")
print(audit.compliance_report_markdown())

# ─────────────────────────────────────────────────────────────────────────
# Signed export bundle for regulator handoff
# ─────────────────────────────────────────────────────────────────────────

compliance_key = generate_keypair()
signed_bundle = audit.export_signed(key=compliance_key, purpose="ndpc_audit_2026q2")
print(f"\nSigned audit bundle ({len(signed_bundle)} chars).")
print("The bundle is a JWS compact-form envelope. The NDPC (or any downstream")
print(f"auditor) can verify it offline against the compliance officer's did:key")
print(f"({compliance_key.did_key[:30]}...) and trust that the audit events")
print("haven't been tampered with since signing. No PII to leak in the bundle —")
print("only category labels, span offsets, and document hashes.")

# Sanity-check we can verify our own export
verified = VerifyExtractWorkflow(strict=False).process(signed_bundle)
print(f"\nSelf-verification: signature_valid={verified.signature_valid}")
