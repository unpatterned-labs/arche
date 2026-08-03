# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""SD-JWT-VC holder binding (KB-JWT) — replay-proof PII presentation."""

import pytest
from arche.attest import attest, present_attestation, verify_attestation
from arche.canonical import Reference
from arche.credentials.sd_jwt import present as sd_present
from arche.resolve.coreference import coref_references
from arche.sign.keys import generate_keypair

_KEY = b"kb-jwt-test-issuer-key-32-bytes!"


def _bound(holder):
    """A keyed decision issued as an SD-JWT bound to `holder`, both PII claims disclosable."""
    issuer = generate_keypair()
    d = coref_references(
        Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "NIN-9001"}),
        Reference.from_record({"full_name": "Ngozi Okonkwo", "national_id": "NIN-9001"}),
        jurisdiction="NG", issuer_key=_KEY,
    )
    return attest(d, issuer, mode="sd-jwt", include_subject=True, holder_key=holder)


def test_key_bound_presentation_verifies():
    holder = generate_keypair()
    pres = present_attestation(_bound(holder), disclose=["national_id"],
                               holder_key=holder, aud="verifier-x", nonce="n-1")
    r = verify_attestation(pres, require_key_binding=True,
                           expected_aud="verifier-x", expected_nonce="n-1")
    assert r.valid and r.key_bound
    assert r.holder_did == holder.did_key
    assert r.claims["national_id"] == "NIN-9001"


def test_replayed_nonce_is_rejected():
    holder = generate_keypair()
    pres = present_attestation(_bound(holder), disclose=["national_id"],
                               holder_key=holder, aud="verifier-x", nonce="n-1")
    r = verify_attestation(pres, require_key_binding=True,
                           expected_aud="verifier-x", expected_nonce="STALE")
    assert not r.valid and "nonce" in (r.error or "")


def test_wrong_audience_is_rejected():
    holder = generate_keypair()
    pres = present_attestation(_bound(holder), disclose=["national_id"],
                               holder_key=holder, aud="verifier-x", nonce="n-1")
    r = verify_attestation(pres, require_key_binding=True,
                           expected_aud="OTHER-VERIFIER", expected_nonce="n-1")
    assert not r.valid and "aud" in (r.error or "")


def test_bearer_presentation_rejected_when_binding_required():
    holder = generate_keypair()
    bearer = sd_present(_bound(holder).compact, disclose=["national_id"])  # no KB-JWT
    r = verify_attestation(bearer, require_key_binding=True,
                           expected_aud="verifier-x", expected_nonce="n-1")
    assert not r.valid and "key binding required" in (r.error or "")


def test_forged_kb_with_wrong_key_is_rejected():
    holder, attacker = generate_keypair(), generate_keypair()
    signed = _bound(holder)
    forged = present_attestation(signed, disclose=["national_id"],
                                 holder_key=attacker, aud="verifier-x", nonce="n-1")
    r = verify_attestation(forged, require_key_binding=True,
                           expected_aud="verifier-x", expected_nonce="n-1")
    assert not r.valid and "signature" in (r.error or "")


def test_kb_jwt_binds_to_the_exact_disclosures():
    # sd_hash defence: an attacker can't splice extra disclosures under a KB-JWT
    # that was signed over a smaller set.
    holder = generate_keypair()
    signed = _bound(holder)
    pres = present_attestation(signed, disclose=["national_id"],
                               holder_key=holder, aud="v", nonce="n")
    extra = sd_present(signed.compact, disclose=["full_name"]).split("~")[1]  # full_name disclosure
    parts = pres.split("~")  # [JWS, disc_national_id, KB]
    tampered = "~".join(parts[:-1] + [extra, parts[-1]])  # splice full_name before the KB
    r = verify_attestation(tampered, require_key_binding=True,
                           expected_aud="v", expected_nonce="n")
    assert not r.valid and "sd_hash" in (r.error or "")


def test_present_requires_aud_and_nonce_with_holder_key():
    holder = generate_keypair()
    with pytest.raises(ValueError, match="aud and nonce"):
        present_attestation(_bound(holder), holder_key=holder, aud=None, nonce="n")  # type: ignore[arg-type]


def test_bound_credential_needs_no_expiry():
    # Binding is a stronger anti-replay than expiry, so holder_key satisfies the
    # include_subject guard without expires_at.
    holder = generate_keypair()
    signed = _bound(holder)  # no expires_at, has holder_key — must not raise
    assert signed.mode == "sd-jwt"


def test_bound_credential_rejects_bearer_downgrade_even_without_flag():
    # HIGH-1: a cnf-bearing credential DEMANDS binding. Stripping the KB-JWT and
    # presenting as bearer must fail even if the verifier forgets require_key_binding.
    holder = generate_keypair()
    bearer = sd_present(_bound(holder).compact, disclose=["national_id"])  # KB stripped
    r = verify_attestation(bearer)  # no require_key_binding, no nonce
    assert not r.valid and "key binding" in (r.error or "")


def test_require_binding_without_expected_nonce_fails_closed():
    # HIGH-2: enforcing binding without supplying the challenge nonce must fail,
    # not silently skip the anti-replay check.
    holder = generate_keypair()
    pres = present_attestation(_bound(holder), disclose=["national_id"],
                               holder_key=holder, aud="v", nonce="n")
    r = verify_attestation(pres, require_key_binding=True, expected_aud="v")  # nonce omitted
    assert not r.valid and "nonce" in (r.error or "")


def test_require_binding_without_expected_aud_fails_closed():
    # Symmetric to the nonce guard: enforced binding also requires the audience.
    holder = generate_keypair()
    pres = present_attestation(_bound(holder), disclose=["national_id"],
                               holder_key=holder, aud="v", nonce="n")
    r = verify_attestation(pres, require_key_binding=True, expected_nonce="n")  # aud omitted
    assert not r.valid and "aud" in (r.error or "")


def test_future_dated_kb_jwt_is_rejected():
    # MED-3: a KB-JWT minted with a far-future iat must not pass freshness.
    from datetime import UTC, datetime, timedelta

    from arche.credentials.sd_jwt import present as sd_present_fn
    from arche.credentials.sd_jwt import verify_sd_jwt
    holder = generate_keypair()
    future = datetime.now(UTC) + timedelta(days=365)
    pres = sd_present_fn(_bound(holder).compact, disclose=["national_id"],
                         holder_key=holder, aud="v", nonce="n", issued_at=future)
    r = verify_sd_jwt(pres, require_key_binding=True, expected_aud="v", expected_nonce="n")
    assert not r.valid and "future" in (r.error or "")


def test_unbound_bearer_still_works_backward_compatible():
    # No holder binding anywhere: still a valid (bearer) SD-JWT.
    from datetime import datetime
    issuer = generate_keypair()
    d = coref_references(
        Reference.from_record({"full_name": "Ada Obi", "national_id": "NIN-1"}),
        Reference.from_record({"full_name": "Ada Obi", "national_id": "NIN-1"}),
        jurisdiction="NG", issuer_key=_KEY,
    )
    sd = attest(d, issuer, mode="sd-jwt", include_subject=["national_id"],
                expires_at=datetime(2030, 1, 1))
    r = verify_attestation(sd_present(sd.compact, disclose=["national_id"]))
    assert r.valid and not r.key_bound
