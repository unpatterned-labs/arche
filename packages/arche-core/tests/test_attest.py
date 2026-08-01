# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for signed co-reference attestations (`arche.attest`)."""

from datetime import datetime

import pytest
from arche.attest import attest, verify_attestation
from arche.canonical import Reference
from arche.credentials.sd_jwt import present
from arche.resolve.coreference import coref_references
from arche.sign.keys import generate_keypair

_ISSUER_KEY = b"attestation-test-issuer-key-32b!"  # >= 32 bytes
_EXP = datetime(2030, 1, 1)


def _decision():
    a = Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "NIN-9001"})
    b = Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "NIN-9001"})
    return coref_references(a, b, jurisdiction="NG", issuer_key=_ISSUER_KEY)


def test_jws_attestation_round_trips_and_carries_decision():
    kp = generate_keypair()
    d = _decision()
    signed = attest(d, kp, mode="jws")
    r = verify_attestation(signed.compact)
    assert r.valid
    assert r.mode == "jws"
    assert r.decision_id == d.decision_id
    assert r.reproducible is True
    assert r.claims["decision"] == "same_entity"


def test_jws_attestation_is_pii_free_by_default():
    kp = generate_keypair()
    signed = attest(_decision(), kp, mode="jws")
    # No raw PII anywhere in the signed compact form.
    assert "Ngozi" not in signed.compact
    assert "Okonkwo" not in signed.compact
    assert "NIN-9001" not in signed.compact
    # The verified claims carry ids + numbers, never the raw name/id.
    r = verify_attestation(signed.compact)
    assert "Ngozi" not in str(r.claims)
    # C1: the PII-derived ids are HMAC-keyed, so they can't be brute-forced back
    # to the source record without the issuer key.
    assert r.claims["reference_id_a"].startswith("ref:hmac-sha256:")
    assert r.claims["decision_id"].startswith("dec:hmac-sha256:")


def test_jws_attestation_is_reproducible():
    kp = generate_keypair()
    d = _decision()
    # Same decision, same key, no timestamp -> identical signed bytes.
    assert attest(d, kp, mode="jws").compact == attest(d, kp, mode="jws").compact


def test_include_subject_rejected_in_jws_mode():
    kp = generate_keypair()
    with pytest.raises(ValueError, match="sd-jwt"):
        attest(_decision(), kp, mode="jws", include_subject=True)


def test_attest_refuses_keyless_decision():
    # C1 enforcement: a decision produced WITHOUT an issuer_key has brute-forceable
    # sha256 ids; attest must refuse to sign it as a (nominally PII-free) artifact.
    kp = generate_keypair()
    keyless = coref_references(
        Reference.from_record({"full_name": "Ada Obi", "national_id": "NIN-1"}),
        Reference.from_record({"full_name": "Ada Obi", "national_id": "NIN-1"}),
        jurisdiction="NG",  # no issuer_key
    )
    assert ":sha256:" in keyless.decision_id  # keyless
    with pytest.raises(ValueError, match="keyless"):
        attest(keyless, kp, mode="jws")
    # ...but an explicit opt-in signs a LOCAL, non-shareable attestation.
    assert verify_attestation(attest(keyless, kp, mode="jws", allow_unkeyed=True).compact).valid


def test_sd_jwt_subject_requires_expiry():
    # A PII-bearing bearer credential must carry an expiry (H2).
    kp = generate_keypair()
    with pytest.raises(ValueError, match="expires_at"):
        attest(_decision(), kp, mode="sd-jwt", include_subject=["national_id"])


def test_tampered_attestation_fails_verification():
    kp = generate_keypair()
    signed = attest(_decision(), kp, mode="jws")
    head, body, sig = signed.compact.split(".")
    tampered = f"{head}.{body}.{'A' * len(sig)}"
    assert verify_attestation(tampered).valid is False


def test_sd_jwt_selective_disclosure_of_pii():
    kp = generate_keypair()
    d = _decision()
    signed = attest(d, kp, mode="sd-jwt", include_subject=["national_id"], expires_at=_EXP)
    assert signed.mode == "sd-jwt"

    # Full presentation discloses the opted-in national_id...
    full = verify_attestation(signed.compact)
    assert full.valid
    assert full.claims.get("national_id") == "NIN-9001"
    assert full.decision_id == d.decision_id

    # ...but a presentation that discloses NOTHING hides it (masked by default).
    withheld = present(signed.compact, disclose=[])
    r = verify_attestation(withheld)
    assert r.valid
    assert "national_id" not in r.claims
    assert r.claims["decision_id"] == d.decision_id  # the decision stays visible


def test_sd_jwt_marks_non_reproducible_semantics_distinct_from_jws():
    kp = generate_keypair()
    d = _decision()
    jws = verify_attestation(attest(d, kp, mode="jws").compact)
    sdj = verify_attestation(attest(d, kp, mode="sd-jwt").compact)
    assert jws.reproducible is True
    assert sdj.reproducible is False  # sd-jwt attests provenance, not byte-repro
