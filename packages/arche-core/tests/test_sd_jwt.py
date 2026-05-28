# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.credentials.sd_jwt — SD-JWT-VC selective disclosure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arche import Pipeline
from arche.credentials import (
    SDJWTResult,
    SDJWTVerifyResult,
    envelope_to_sd_jwt,
    issue_sd_jwt,
    present,
    verify_sd_jwt,
)
from arche.sign import ArcheSignedDocument, generate_keypair


# ── Issue + verify roundtrip ────────────────────────────────────────────────


def test_issue_sd_jwt_returns_compact_and_jws_and_disclosures():
    kp = generate_keypair()
    r = issue_sd_jwt(
        claims={"name": "Adesola", "nin": "12345678901"},
        issuer_key=kp,
    )
    assert isinstance(r, SDJWTResult)
    # Compact form is JWS~disclosure~disclosure~ with trailing ~
    assert r.compact.endswith("~")
    assert r.compact.count("~") == 3
    assert len(r.disclosures) == 2
    # JWS itself is 3 segments
    assert r.jws.count(".") == 2


def test_verify_recovers_disclosed_claims_when_all_disclosures_present():
    kp = generate_keypair()
    r = issue_sd_jwt(
        claims={"name": "Adesola", "nin": "12345678901", "jurisdiction": "NG"},
        issuer_key=kp,
    )
    v = verify_sd_jwt(r.compact)
    assert v.valid is True
    assert v.issuer_did == kp.did_key
    assert v.disclosed_claims == {
        "name": "Adesola",
        "nin": "12345678901",
        "jurisdiction": "NG",
    }
    assert v.vc_type == "ArcheDetectionCredential"


def test_verify_includes_visible_claims():
    """Claims NOT in disclosable_claims stay in the JWT payload (visible)."""
    kp = generate_keypair()
    r = issue_sd_jwt(
        claims={"name": "Adesola", "nin": "12345678901"},
        issuer_key=kp,
        disclosable_claims=["nin"],  # name is always visible
    )
    v = verify_sd_jwt(r.compact)
    assert v.valid is True
    assert v.visible_claims["name"] == "Adesola"
    assert v.disclosed_claims["nin"] == "12345678901"


def test_verify_combines_claims_property():
    kp = generate_keypair()
    r = issue_sd_jwt(
        claims={"a": 1, "b": 2, "c": 3},
        issuer_key=kp,
        disclosable_claims=["c"],
    )
    v = verify_sd_jwt(r.compact)
    assert v.claims == {"a": 1, "b": 2, "c": 3, "iss": kp.did_key,
                        "vct": "ArcheDetectionCredential"}


# ── Selective disclosure (the headline feature) ─────────────────────────────


def test_holder_can_present_subset_of_disclosures():
    """Holder selectively discloses one claim, hides another. Issuer
    signature still binds the whole — the verifier sees only what
    the holder forwarded."""
    kp = generate_keypair()
    issued = issue_sd_jwt(
        claims={
            "name": "Adesola Okonkwo",
            "nin_present": True,
            "bvn_present": True,
            "health_data_present": True,
        },
        issuer_key=kp,
    )

    # Holder presents only the bvn claim
    presentation = present(issued.compact, disclose=["bvn_present"])

    v = verify_sd_jwt(presentation)
    assert v.valid is True
    assert v.disclosed_claims == {"bvn_present": True}
    assert "nin_present" not in v.disclosed_claims
    assert "health_data_present" not in v.disclosed_claims


def test_holder_can_present_empty_disclosure_set():
    kp = generate_keypair()
    issued = issue_sd_jwt(
        claims={"sensitive": "x"},
        issuer_key=kp,
    )
    presentation = present(issued.compact, disclose=[])
    v = verify_sd_jwt(presentation)
    # Signature is still valid, just no claims disclosed
    assert v.valid is True
    assert v.disclosed_claims == {}


def test_holder_present_none_keeps_all_disclosures():
    kp = generate_keypair()
    issued = issue_sd_jwt(
        claims={"a": 1, "b": 2},
        issuer_key=kp,
    )
    presentation = present(issued.compact)
    assert presentation == issued.compact
    v = verify_sd_jwt(presentation)
    assert v.disclosed_claims == {"a": 1, "b": 2}


# ── Tamper detection ───────────────────────────────────────────────────────


def test_modified_disclosure_rejected():
    """A disclosure that doesn't hash to any _sd entry is a tamper signal."""
    kp = generate_keypair()
    issued = issue_sd_jwt(
        claims={"name": "Adesola"},
        issuer_key=kp,
    )
    # Forge a disclosure for a claim not in _sd
    from arche.credentials.sd_jwt import _make_disclosure
    forged_disclosure, _ = _make_disclosure("name", "Mallory")

    jws_part, _, _ = issued.compact.partition("~")
    forged_compact = f"{jws_part}~{forged_disclosure}~"

    v = verify_sd_jwt(forged_compact)
    assert v.valid is False
    assert "did not match _sd hashes" in (v.error or "")


def test_tampered_jws_rejected():
    """Modifying the JWS payload after signing breaks verification."""
    kp = generate_keypair()
    issued = issue_sd_jwt(claims={"x": 1}, issuer_key=kp)

    # Swap header to corrupt signing input
    jws_part, _, rest = issued.compact.partition("~")
    header, _, sig = jws_part.split(".")
    # Modify a single character in the signature
    sig_corrupt = sig[:-2] + ("XX" if sig[-2:] != "XX" else "YY")
    corrupted_compact = f"{header}..{sig_corrupt}~{rest}"

    v = verify_sd_jwt(corrupted_compact)
    assert v.valid is False


def test_wrong_vc_type_rejected():
    kp = generate_keypair()
    issued = issue_sd_jwt(
        claims={"x": 1}, issuer_key=kp,
        vc_type="ArcheDetectionCredential",
    )
    v = verify_sd_jwt(issued.compact, expected_vc_type="ArcheDSARCredential")
    assert v.valid is False
    assert "vct mismatch" in (v.error or "")


def test_expired_credential_rejected():
    kp = generate_keypair()
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    issued = issue_sd_jwt(
        claims={"x": 1},
        issuer_key=kp,
        expires_at=past,
    )
    v = verify_sd_jwt(issued.compact)
    assert v.valid is False
    assert v.expired is True


def test_expiry_check_can_be_disabled():
    kp = generate_keypair()
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    issued = issue_sd_jwt(
        claims={"x": 1},
        issuer_key=kp,
        expires_at=past,
    )
    v = verify_sd_jwt(issued.compact, check_expiry=False)
    assert v.valid is True


# ── Envelope -> SD-JWT-VC bridge ───────────────────────────────────────────


def test_envelope_to_sd_jwt_round_trip():
    """An ArcheSignedDocument can be re-framed as an SD-JWT-VC and verified."""
    kp = generate_keypair()
    pipeline = Pipeline(jurisdiction="NG", tokenize_salt="t")
    result = pipeline.process("NIN 12345678901 for Adesola.")

    envelope = ArcheSignedDocument.from_pipeline_result(
        result, issuer_did=kp.did_key, purpose="dsar_response",
    )

    sd_jwt = envelope_to_sd_jwt(envelope, issuer_key=kp)
    v = verify_sd_jwt(sd_jwt.compact)
    assert v.valid is True
    assert v.issuer_did == kp.did_key
    assert v.vc_type == "ArcheDetectionCredential"

    # All envelope fields recoverable via disclosures + visible claims
    all_claims = v.claims
    assert all_claims["doc_hash"] == result.document_hash
    assert all_claims["jurisdiction"] == "NG"


def test_envelope_to_sd_jwt_holder_can_hide_redacted_text():
    """Selective disclosure: the holder can present the metadata
    (jurisdiction, statute) without leaking the redacted text."""
    kp = generate_keypair()
    pipeline = Pipeline(jurisdiction="NG")
    result = pipeline.process("NIN 12345678901.")

    envelope = ArcheSignedDocument.from_pipeline_result(
        result, issuer_did=kp.did_key, purpose="audit",
    )
    sd_jwt = envelope_to_sd_jwt(envelope, issuer_key=kp)

    # Holder discloses jurisdiction + purpose, hides redacted_text + detections
    presentation = present(
        sd_jwt.compact,
        disclose=["jurisdiction", "purpose"],
    )
    v = verify_sd_jwt(presentation)
    assert v.valid is True
    assert v.disclosed_claims == {
        "jurisdiction": "NG",
        "purpose": "audit",
    }
    assert "redacted_text" not in v.disclosed_claims
    assert "detections" not in v.disclosed_claims
