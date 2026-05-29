"""Example 04 — SD-JWT-VC selective disclosure.

The wallet-interop arche-core v0.2 capability: emit a Verifiable
Credential in the IETF SD-JWT-VC format (the same format EUDI Wallet
ARF and MOSIP Inji standardize on). The holder controls which claims
to disclose to each verifier; the issuer's signature still binds the
whole credential regardless of what's disclosed.

Run::

    python examples/04_sd_jwt_credential.py
"""

from arche import Pipeline
from arche.credentials import envelope_to_sd_jwt, present, verify_sd_jwt
from arche.sign import ArcheSignedDocument, generate_keypair

# ──────────────────────────────────────────────────────────────────────
# Issuer (e.g., a Nigerian bank) issues a credential
# ──────────────────────────────────────────────────────────────────────

bank_key = generate_keypair()
print(f"Issuer DID: {bank_key.did_key}\n")

# Run the document through the framework and wrap the result in a
# signed envelope — exactly like example 02.
pipeline = Pipeline(jurisdiction="NG", tokenize_salt="sterling_2026")
result = pipeline.process(
    "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012."
)
envelope = ArcheSignedDocument.from_pipeline_result(
    result,
    issuer_did=bank_key.did_key,
    purpose="kyc_attestation",
)

# Re-frame the envelope as an SD-JWT-VC.  Every field becomes
# individually disclosable.
sd_jwt = envelope_to_sd_jwt(envelope, issuer_key=bank_key)
print(f"Issued SD-JWT-VC ({len(sd_jwt.compact)} chars), "
      f"with {len(sd_jwt.disclosures)} disclosable claims.\n")

# ──────────────────────────────────────────────────────────────────────
# Holder presents two different subsets to two different verifiers
# ──────────────────────────────────────────────────────────────────────

# Verifier #1 — a compliance auditor only needs the statute + purpose
present_1 = present(sd_jwt.compact, disclose=["jurisdiction", "purpose"])

v1 = verify_sd_jwt(present_1)
print("Verifier #1 (compliance auditor) sees:")
print(f"  signature_valid:  {v1.valid}")
print(f"  disclosed_claims: {v1.disclosed_claims}")
print(f"  detections in v1.claims? "
      f"{'detections' in v1.claims}  (hidden by holder)")
print()

# Verifier #2 — a downstream KYC reviewer needs the redacted text + categories
present_2 = present(
    sd_jwt.compact,
    disclose=["jurisdiction", "purpose", "redacted_text", "policy_outcomes"],
)

v2 = verify_sd_jwt(present_2)
print("Verifier #2 (KYC reviewer) sees:")
print(f"  signature_valid:  {v2.valid}")
print(f"  disclosed_claims: {sorted(v2.disclosed_claims.keys())}")
print(f"  redacted_text:    {v2.disclosed_claims.get('redacted_text')}")
print()

print("Both verifiers can confirm the credential was issued by the bank")
print("(signature still binds the whole thing). Each saw only what the")
print("holder chose to disclose — selective disclosure with cryptographic")
print("integrity.")
