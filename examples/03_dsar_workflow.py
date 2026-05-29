"""Example 03 — Citizen-side Data Subject Access Request (NDPA / POPIA / KE-DPA / GH-DPA).

Adesola is a Nigerian citizen. She wants to know what data Sterling Bank holds about her and what data MTN Nigeria holds about her. NDPA-2023 §34 gives her the right to ask, and the bank's DPO has 30 days to respond. In theory she can exercise this right today. In practice she can't, because the process is invisible: there's no template letter, no published DPO inbox at most organisations, no cryptographic proof her request actually came from her, and no shared format the DPO knows how to process.

WITHOUT arche-core, here's how this currently works:

    1. Adesola searches for a DSAR template online. She finds a UK ICO template
       which cites the wrong statute. She tries to localise it. She isn't a lawyer.
    2. She emails the request from her Gmail to dpo@sterlingbank.ng. The DPO has
       no way to verify the request actually came from the NIN holder; anyone
       with her email could have sent it.
    3. The DPO might respond. Or might not. There's no deadline tracking, no
       escalation path, no shared protocol.
    4. If she tries to file the same request with MTN Nigeria, she rewrites the
       letter from scratch because nothing carries over.
    5. If she ever needs to prove to a regulator she filed the request on a
       specific date, she has only her Gmail "Sent" folder. Easy to fake; not
       legally compelling.

WITH arche-core, the citizen runs the workflow once and gets:

    - A statute-grounded letter for each target organisation, citing the exact
      section of NDPA-2023 (or POPIA / KE-DPA / GH-DPA depending on jurisdiction).
    - Each letter wrapped in a JWS envelope signed with the citizen's own did:key
      so the DPO has cryptographic proof of provenance.
    - A 30-day deadline computed correctly per statute.
    - One workflow, multiple targets, all letters generated in one call.

Stage 1 ships `dispatch_mode="draft_only"`. The workflow drafts and signs the letters; the citizen reviews and emails them manually. Autonomous dispatch is post-beta work with explicit consent mechanisms — drafting the letter is one thing; sending it on someone's behalf is another.

Run::

    python examples/03_dsar_workflow.py
"""

from arche.sign import VerifyExtractWorkflow, generate_keypair
from arche.workflow import DSAROrganization, DSARRequestor, DSARWorkflow

# Citizen-held key — typically generated once and stored locally. In a real
# deployment this lives in a citizen wallet app; for the demo we generate it
# fresh on every run.
citizen_key = generate_keypair()
print(f"Citizen DID: {citizen_key.did_key}\n")

# Frame the request once; the workflow fans out to every target.
workflow = DSARWorkflow(
    jurisdiction="NG",                       # auto-resolves NDPA-2023
    requestor=DSARRequestor(
        name="Adesola Okonkwo",
        identifier_label="NIN",
        identifier_value="12345678901",
        email="adesola@example.com",
        phone="+234 803 555 7890",
    ),
    request_type="access",                   # access | rectification | erasure | portability | objection
    targets=[
        DSAROrganization(name="Sterling Bank Limited",
                         dpo_email="dpo@sterlingbank.ng"),
        DSAROrganization(name="MTN Nigeria Communications",
                         dpo_email="dpo@mtn.ng"),
    ],
)

print("=== Workflow plan ===")
import json
print(json.dumps(workflow.describe(), indent=2))

# Generate drafts (and signed envelopes) for every target.
result = workflow.run(citizen_key)

print(f"\n=== Drafts generated: {len(result.drafts)} ===\n")

for draft in result.drafts:
    print("-" * 72)
    print(f"Target:    {draft.target.name}")
    print(f"Deadline:  {draft.deadline.strftime('%Y-%m-%d')}")
    print(f"Citation:  {draft.citation}")
    print("-" * 72)
    print(draft.letter_text)
    print()

# Each draft carries a signed envelope. The DPO can verify offline and trust
# that the request originated from the holder of `citizen_key` — not from
# anyone who has Adesola's email password.
print("-" * 72)
print("DPO-side verification (one draft):")
print("-" * 72)

verifier = VerifyExtractWorkflow(
    require_purpose=f"dsar_{result.request_type}",
    require_jurisdiction=result.jurisdiction,
)

verified = verifier.process(result.drafts[0].signed_envelope)
print(f"  Signature valid:     {verified.signature_valid}")
print(f"  Issued by citizen:   {verified.issuer_did}")
print(f"  Statute:             {verified.statute_at_signing}")
print(f"  Purpose:             {verified.envelope.purpose}")
print(f"  Issued at:           {verified.issued_at}")
print(f"  Expires at:          {verified.envelope.expires_at}")
print()
print("The DPO can now act on a tamper-evident, jurisdiction-aware DSAR")
print("with cryptographic provenance — suitable for showing to the NDPC")
print("if there's ever a question about whether the request was genuine.")

# Want the same workflow for South Africa? Change jurisdiction="NG" to "ZA"
# and the letters cite POPIA §23 instead of NDPA-2023 §34. Same code, same
# wallet key, different statute, different deadline computation. Kenya DPA
# §26 for KE; Ghana DPA §35 for GH.
