"""Example 01 — Pipeline with NDPA-2023 enforcement.

You're a Lagos fintech engineer. Your CTO just got off a call with the NDPC compliance team and now every customer-intake record that lands in your data warehouse needs to be redacted before it gets there. The auditor will come back asking "show me the rule that fired." You have a sprint to ship this.

WITHOUT arche-core, this is roughly the shape of what you'd write::

    import re

    NIN_RE = re.compile(r"\\bNIN[\\s:]*(\\d{11})\\b")
    BVN_RE = re.compile(r"\\bBVN[\\s:]*(\\d{11})\\b")
    PHONE_RE = re.compile(r"\\b(?:\\+234|0)\\s?[789]\\d{9}\\b")
    RC_RE = re.compile(r"\\bRC[\\s:]*(\\d{6,8})\\b")
    # ... and one for TIN, voter PVC, drivers licence ...

    def validate_nin(nin: str) -> bool:
        # NIMC publishes no public checksum spec; you write a length + prefix check
        return len(nin) == 11 and nin.isdigit()

    def validate_bvn(bvn: str) -> bool:
        return len(bvn) == 11 and bvn.startswith("22")

    # Now you read NDPA §30 and decide which categories need which action.
    # NIN and BVN are sensitive personal data → mask. RC is public-record → retain.
    # Phone is contact info → tokenize. You hardcode the mapping.

    def redact_ndpa(text: str) -> tuple[str, list[dict]]:
        decisions = []
        text = NIN_RE.sub(lambda m: ("[NIN]", decisions.append({...}))[0], text)
        text = BVN_RE.sub(...)
        # ... 40 more lines of tokenization-vs-masking-vs-retention logic ...
        return text, decisions

    def audit_without_storing_pii(text_hash: str, decisions: list[dict]) -> None:
        # Make sure you log category + span but NEVER the value. Easy to mess up.
        ...

You ship this. Six months later NIMC publishes an amendment that changes
the NIN format. You update the regex. The next person who joins the team
doesn't know NIN spec versus BVN spec. The auditor asks which statute
section line 47 of redact_ndpa() implements; you don't remember.

WITH arche-core, that whole module is three lines plus a config file you
read but don't write.

Run::

    python examples/01_pipeline_ndpa.py
"""

from arche import Pipeline

# Configure for Nigeria. The statute auto-resolves to NDPA-2023.
# tokenize_salt is a per-organization secret — different orgs get different
# tokens for the same input so audit data can't be joined across deployments
# without consent.
pipeline = Pipeline(
    jurisdiction="NG",
    tokenize_salt="sterling_bank_2026",
)

text = (
    "Customer Adesola Okonkwo registered with NIN 12345678901 "
    "and BVN 22156789012. Contact phone 0803 555 7890. "
    "Company: RC 245678."
)

result = pipeline.process(text)

# --- What the Pipeline returns ----------------------------------------

print("=== Pipeline.describe() ===")
import json
print(json.dumps(pipeline.describe(), indent=2))

print("\n=== Detections (every one carries a statute citation) ===")
for d in result.detections:
    print(f"  {d.category:25s} [{d.start:3d}:{d.end:3d}] "
          f"conf={d.confidence:.2f} class={d.identity_class:12s} "
          f"text={d.text!r}")

print("\n=== Policy outcomes — these are the rules that fired (per NDPA-2023) ===")
for o in result.policy_outcomes:
    print(f"  {o.category:25s} -> {o.action:10s} "
          f"({o.statute_reference[:60]}...)")

print("\n=== Redacted text — safe to ship to the warehouse ===")
print(f"  {result.redacted_text}")

print("\n=== Provenance — this is what the auditor asks for ===")
print(f"  document_hash:    {result.document_hash[:16]}...")
print(f"  audit entries:    {len(result.audit_log)}")
print(f"  pipeline version: {result.metadata['pipeline_version']}")
print(f"  statute:          {result.metadata['statute_id']} "
      f"v{result.metadata['statute_version']}")

# The same code works for ZA (POPIA), KE (Kenya DPA), GH (Ghana DPA).
# Change `jurisdiction="NG"` to one of those and you get a different statute
# YAML loaded automatically. The redaction logic doesn't change. The audit
# log row format doesn't change. Only the citations change.
