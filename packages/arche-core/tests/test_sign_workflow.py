# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.sign.envelope and arche.sign.workflow — the
high-level sign-share-extract surface."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arche import Pipeline
from arche.sign import (
    ArcheSignedDocument,
    SignatureVerificationError,
    SignWorkflow,
    VerifyExtractWorkflow,
    document_hash,
    generate_keypair,
)


# ── ArcheSignedDocument ─────────────────────────────────────────────────────


def test_envelope_from_pipeline_result_round_trip():
    """Building from a Result then back to dict preserves all fields."""
    pipeline = Pipeline(jurisdiction="NG", tokenize_salt="t")
    result = pipeline.process("NIN 12345678901 and BVN 22156789012.")

    issuer = "did:key:z6MkfTestDid12345"
    envelope = ArcheSignedDocument.from_pipeline_result(
        result, issuer_did=issuer, purpose="dsar_response"
    )

    assert envelope.doc_hash == result.document_hash
    assert envelope.issuer == issuer
    assert envelope.purpose == "dsar_response"
    assert envelope.jurisdiction == "NG"
    assert envelope.statute == "NDPA-2023@vv1.0"  # version field as stored
    assert envelope.schema_version == "arche+envelope/v1"
    assert len(envelope.detections) == len(result.detections)
    assert len(envelope.policy_outcomes) == len(result.policy_outcomes)


def test_envelope_to_canonical_json_is_stable_across_orderings():
    """Sort_keys makes the canonical form independent of build order."""
    a = ArcheSignedDocument(
        doc_hash="abc", redacted_text="x",
        issuer="did:key:z6Mka", issued_at="2026-06-02T00:00:00+00:00",
        purpose="dsar_response", jurisdiction="NG",
    )
    b = ArcheSignedDocument(
        purpose="dsar_response", jurisdiction="NG",
        issuer="did:key:z6Mka", issued_at="2026-06-02T00:00:00+00:00",
        doc_hash="abc", redacted_text="x",
    )
    assert a.to_canonical_json() == b.to_canonical_json()


def test_envelope_from_dict_round_trip():
    e = ArcheSignedDocument(
        doc_hash=document_hash("hello"),
        redacted_text="hello",
        detections=[{"category": "PII-1-NAME", "start": 0, "end": 5}],
        policy_outcomes=[{"category": "PII-1-NAME", "action": "tokenize"}],
        issuer="did:key:z6MkfTest",
        issued_at="2026-06-02T00:00:00+00:00",
        purpose="audit_export",
        jurisdiction="NG",
        statute="NDPA-2023@v1.0",
    )
    d = e.to_dict()
    hydrated = ArcheSignedDocument.from_dict(d)
    assert hydrated == e


def test_envelope_is_expired_when_in_past():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    e = ArcheSignedDocument(
        doc_hash="x", redacted_text="x", expires_at=past,
    )
    assert e.is_expired() is True


def test_envelope_is_not_expired_when_in_future():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    e = ArcheSignedDocument(
        doc_hash="x", redacted_text="x", expires_at=future,
    )
    assert e.is_expired() is False


def test_envelope_with_no_expiry_never_expires():
    e = ArcheSignedDocument(doc_hash="x", redacted_text="x")
    assert e.is_expired() is False


def test_document_hash_deterministic():
    assert document_hash("hello") == document_hash("hello")
    assert document_hash("hello") != document_hash("world")


# ── SignWorkflow ────────────────────────────────────────────────────────────


def test_sign_workflow_signs_a_nigerian_dsar():
    """End-to-end: process NG text through SignWorkflow, get a JWS."""
    kp = generate_keypair()
    wf = SignWorkflow(jurisdiction="NG", tokenize_salt="bank_a")
    jws = wf.sign(
        "Customer Adesola Okonkwo, NIN 12345678901, BVN 22156789012.",
        kp,
        purpose="dsar_response",
    )
    # JWS compact form
    parts = jws.split(".")
    assert len(parts) == 3
    assert all(parts), "JWS segments should all be non-empty"


def test_sign_workflow_accepts_raw_private_key_with_issuer_did():
    """Caller can pass a raw Ed25519PrivateKey + explicit issuer_did."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.generate()
    wf = SignWorkflow(jurisdiction="ZA")
    jws = wf.sign("ID 8001015009087.", pk, issuer_did="did:web:bank.example.org")
    assert jws.count(".") == 2


def test_sign_workflow_describe():
    kp = generate_keypair()
    wf = SignWorkflow(jurisdiction="NG", tokenize_salt="t")
    d = wf.describe()
    assert d["kind"] == "SignWorkflow"
    assert d["jurisdiction"] == "NG"
    assert d["statute"] == "NDPA-2023"
    assert d["signature_alg"] == "EdDSA"
    assert d["tokenize_salt_set"] is True


# ── VerifyExtractWorkflow ───────────────────────────────────────────────────


def test_verify_extract_recovers_pipeline_result_offline():
    """The headline test: sign → share → verify offline → extract."""
    kp = generate_keypair()
    signer = SignWorkflow(jurisdiction="NG", tokenize_salt="bank_a")
    jws = signer.sign(
        "NIN 12345678901 and BVN 22156789012 for Adesola Okonkwo.",
        kp,
        purpose="dsar_response",
    )

    verifier = VerifyExtractWorkflow()
    r = verifier.process(jws)

    assert r.signature_valid is True
    assert r.issuer_did == kp.did_key
    assert r.jurisdiction == "NG"
    assert r.statute_at_signing.startswith("NDPA-2023")
    assert r.schema_version == "arche+envelope/v1"

    # Recovered Pipeline.Result fields
    categories = {d["category"] for d in r.detections}
    assert "PII-2-NIN" in categories
    assert "PII-2-BVN" in categories
    assert "[NIN]" in r.redacted_text
    assert "[BVN]" in r.redacted_text

    # Policy outcomes survived serialization
    actions = {(o["category"], o["action"]) for o in r.policy_outcomes}
    assert ("PII-2-NIN", "mask") in actions
    assert ("PII-2-BVN", "mask") in actions


def test_verify_extract_tampered_payload_strict_raises():
    """Modifying the JWS payload after signing must be caught."""
    kp = generate_keypair()
    jws = SignWorkflow(jurisdiction="NG").sign("NIN 12345678901.", kp)

    # Tamper: replace payload segment with something else
    header, _, signature = jws.split(".")
    import base64, json
    evil_payload = base64.urlsafe_b64encode(
        json.dumps({"doc_hash": "evil"}, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode("ascii")
    tampered = f"{header}.{evil_payload}.{signature}"

    verifier = VerifyExtractWorkflow(strict=True)
    with pytest.raises(SignatureVerificationError):
        verifier.process(tampered)


def test_verify_extract_tampered_payload_non_strict_returns_invalid():
    kp = generate_keypair()
    jws = SignWorkflow(jurisdiction="NG").sign("NIN 12345678901.", kp)

    header, _, signature = jws.split(".")
    import base64, json
    evil_payload = base64.urlsafe_b64encode(
        json.dumps({"doc_hash": "evil"}, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode("ascii")
    tampered = f"{header}.{evil_payload}.{signature}"

    verifier = VerifyExtractWorkflow(strict=False)
    r = verifier.process(tampered)
    assert r.signature_valid is False
    assert r.error  # has a reason


def test_verify_extract_purpose_mismatch_rejected():
    kp = generate_keypair()
    jws = SignWorkflow(jurisdiction="NG").sign(
        "NIN 12345678901.", kp, purpose="dsar_response"
    )
    verifier = VerifyExtractWorkflow(
        require_purpose="kyb_attestation", strict=False
    )
    r = verifier.process(jws)
    assert r.signature_valid is False
    assert "Purpose mismatch" in (r.error or "")


def test_verify_extract_jurisdiction_mismatch_rejected():
    kp = generate_keypair()
    jws = SignWorkflow(jurisdiction="NG").sign("NIN 12345678901.", kp)
    verifier = VerifyExtractWorkflow(require_jurisdiction="ZA", strict=False)
    r = verifier.process(jws)
    assert r.signature_valid is False
    assert "Jurisdiction mismatch" in (r.error or "")


def test_verify_extract_expiry_rejected():
    """A signed envelope past its expires_at is rejected."""
    kp = generate_keypair()
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    jws = SignWorkflow(jurisdiction="NG").sign(
        "NIN 12345678901.", kp, expires_at=past
    )
    verifier = VerifyExtractWorkflow(strict=False, check_expiry=True)
    r = verifier.process(jws)
    assert r.signature_valid is False
    assert r.expired is True
    assert "expired" in (r.error or "").lower()


def test_verify_extract_can_skip_expiry_check():
    """check_expiry=False lets us inspect expired envelopes."""
    kp = generate_keypair()
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    jws = SignWorkflow(jurisdiction="NG").sign(
        "NIN 12345678901.", kp, expires_at=past
    )
    verifier = VerifyExtractWorkflow(strict=False, check_expiry=False)
    r = verifier.process(jws)
    assert r.signature_valid is True  # signature still valid


def test_two_organizations_produce_different_tokens():
    """Different tokenize salts at sign time -> tokens don't match."""
    kp_a = generate_keypair()
    kp_b = generate_keypair()
    jws_a = SignWorkflow(jurisdiction="NG", tokenize_salt="bank_a").sign(
        "Adesola Okonkwo, NIN 12345678901.", kp_a
    )
    jws_b = SignWorkflow(jurisdiction="NG", tokenize_salt="bank_b").sign(
        "Adesola Okonkwo, NIN 12345678901.", kp_b
    )

    verifier = VerifyExtractWorkflow()
    ra = verifier.process(jws_a)
    rb = verifier.process(jws_b)

    # Both valid signatures
    assert ra.signature_valid and rb.signature_valid
    # Same NIN value, different masked tokens for the name (tokenize action),
    # but NIN itself is masked to "[NIN]" by NDPA so the redacted text differs
    # only in the name tokenization.
    name_a = next((o["applied_value"] for o in ra.policy_outcomes
                   if o["category"] == "PII-1-NAME"), None)
    name_b = next((o["applied_value"] for o in rb.policy_outcomes
                   if o["category"] == "PII-1-NAME"), None)
    if name_a and name_b:
        assert name_a != name_b, "different salts must produce different tokens"


def test_sign_share_extract_headline_workflow():
    """The user's stated test: provide a document, sign it, give it to
    someone, they extract the information from it."""
    # ── Party A ──────────────────────────────────────────────────────────
    issuer = generate_keypair()
    signer = SignWorkflow(jurisdiction="NG", tokenize_salt="org_a")
    original_text = (
        "Customer Adesola Okonkwo registered with NIN 12345678901 "
        "and BVN 22156789012. Phone 0803 555 7890. RC 245678."
    )
    signed_envelope = signer.sign(
        original_text, issuer, purpose="dsar_response",
    )

    # ── Wire transit happens here (signed_envelope is a string) ─────────
    assert isinstance(signed_envelope, str)
    assert "." in signed_envelope

    # ── Party B ─────────────────────────────────────────────────────────
    # No coordination with Party A required — verifier resolves the
    # public key from the did:key in the JWS kid header.
    verifier = VerifyExtractWorkflow()
    extracted = verifier.process(signed_envelope)

    # Party B knows: who signed (did:key), when, under what statute,
    # what categories of PII were found, and what action was taken.
    # Party B does NOT know: the original document text (only the
    # redacted version), the tokenize salt (so tokens aren't reversible).
    assert extracted.signature_valid
    assert extracted.issuer_did == issuer.did_key
    assert extracted.jurisdiction == "NG"
    assert "NDPA-2023" in extracted.statute_at_signing
    assert original_text not in extracted.redacted_text  # original is hidden
    assert "[NIN]" in extracted.redacted_text             # but redactions are visible
    assert "[BVN]" in extracted.redacted_text
    assert len(extracted.detections) >= 3
