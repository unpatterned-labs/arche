"""Example 02 — Sign, share, extract.

The headline arche-core v0.2 capability: a party signs a document and
its policy-applied detection set; a recipient verifies the signature
offline (no infrastructure, just an Ed25519 verify) and recovers the
redacted text + policy outcomes.

Run::

    python examples/02_sign_share_extract.py
"""

from arche.sign import SignWorkflow, VerifyExtractWorkflow, generate_keypair

# ----------------------------------------------------------------------
# Party A — Bank's compliance officer signs a customer record
# ----------------------------------------------------------------------

bank_key = generate_keypair()                # caller-held; never leaves Party A
print(f"Party A (bank) DID:  {bank_key.did_key}")

signer = SignWorkflow(
    jurisdiction="NG",
    statute="NDPA-2023",
    tokenize_salt="sterling_bank_2026",
)

document = (
    "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012, "
    "phone 0803 555 7890. RC 245678."
)

signed_envelope = signer.sign(
    document,
    bank_key,
    purpose="dsar_response",
)

print(f"\nSigned envelope ({len(signed_envelope)} chars), "
      f"JWS compact form:")
print(f"  {signed_envelope[:80]}...")
print(f"  ...{signed_envelope[-30:]}")

# ----------------------------------------------------------------------
# Wire transit — signed_envelope is a single string. Email it, ship it
# in an HTTP body, encode it in a QR code. The recipient needs nothing
# but the string itself.
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Party B — Recipient verifies offline and extracts policy outcomes
# ----------------------------------------------------------------------

verifier = VerifyExtractWorkflow(
    require_purpose="dsar_response",   # reject envelopes meant for other purposes
    require_jurisdiction="NG",         # reject cross-jurisdiction misuse
    check_expiry=True,
)

extracted = verifier.process(signed_envelope)

print("\n=== Party B view ===")
print(f"  signature_valid:    {extracted.signature_valid}")
print(f"  issuer_did:         {extracted.issuer_did}")
print(f"  statute_at_signing: {extracted.statute_at_signing}")
print(f"  issued_at:          {extracted.issued_at}")
print(f"  jurisdiction:       {extracted.jurisdiction}")
print(f"  expired:            {extracted.expired}")

print("\n  Detections (categories only — original text is hidden):")
for d in extracted.detections:
    print(f"    - {d['category']:25s} conf={d['confidence']:.2f}")

print("\n  Policy outcomes per NDPA-2023:")
for o in extracted.policy_outcomes:
    print(f"    - {o['category']:25s} -> {o['action']}")

print("\n  Redacted text recipient receives:")
print(f"    {extracted.redacted_text}")

print("\nThe recipient knows what was detected and what was redacted, "
      "with cryptographic provenance, but cannot see the original PII "
      "values. The tokenize_salt is held by Party A so tokens can't be "
      "reversed by Party B.")
