# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.sign — Ed25519 keys, did:key encoding, JWS envelope."""

from __future__ import annotations

import json

import pytest

from arche.sign import (
    Keypair,
    VerificationResult,
    decode_did_key,
    encode_did_key,
    export_private_pem,
    export_public_pem,
    generate_keypair,
    load_private_key_pem,
    load_public_key,
    sign,
    verify,
)


# ── Keypair generation + did:key encoding ───────────────────────────────────


def test_generate_keypair_returns_keypair_with_did_key():
    kp = generate_keypair()
    assert isinstance(kp, Keypair)
    assert kp.did_key.startswith("did:key:z6Mk")
    # Ed25519 did:key encodings are always 48-49 chars
    assert 40 <= len(kp.did_key) <= 60


def test_generate_keypair_unique_keys():
    a = generate_keypair()
    b = generate_keypair()
    assert a.did_key != b.did_key


def test_did_key_roundtrip():
    """encode -> decode should yield the original public key bytes."""
    kp = generate_keypair()
    decoded_pk = decode_did_key(kp.did_key)
    assert decoded_pk.public_bytes_raw() == kp.public_key.public_bytes_raw()


def test_decode_did_key_rejects_non_ed25519_prefix():
    # base58btc encoding of a multicodec that isn't 0xed01 (Ed25519)
    with pytest.raises(ValueError, match="not Ed25519"):
        # 0x12 is the SHA2-256 multihash code, definitely not a public key
        decode_did_key("did:key:zQmYwAPJzv5CZsnAzt8auVTLvJB7nQg1ZBP9PB1JTrkpfNg")


def test_decode_did_key_rejects_malformed():
    with pytest.raises(ValueError, match="Not a did:key"):
        decode_did_key("did:web:example.org")


def test_keypair_repr_does_not_leak_private_key():
    kp = generate_keypair()
    r = repr(kp)
    assert "did:key" in r
    assert "PrivateKey" not in r  # actual private bytes shouldn't appear


def test_public_only_drops_private_key():
    kp = generate_keypair()
    pub = kp.public_only()
    assert pub.public_key.public_bytes_raw() == kp.public_key.public_bytes_raw()
    assert pub.did_key == kp.did_key
    # Attempting to use the private key surface raises
    with pytest.raises(RuntimeError, match="public key"):
        pub.private_key.sign(b"x")


# ── PEM round-trip ──────────────────────────────────────────────────────────


def test_export_and_load_private_pem_roundtrip():
    kp = generate_keypair()
    pem = export_private_pem(kp)
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    loaded = load_private_key_pem(pem)
    assert loaded.did_key == kp.did_key


def test_export_private_pem_with_password():
    kp = generate_keypair()
    pem = export_private_pem(kp, password=b"correcthorsebatterystaple")
    assert pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
    loaded = load_private_key_pem(pem, password=b"correcthorsebatterystaple")
    assert loaded.did_key == kp.did_key


def test_load_private_pem_wrong_password_fails():
    kp = generate_keypair()
    pem = export_private_pem(kp, password=b"hunter2")
    with pytest.raises(Exception):  # cryptography raises a specific error
        load_private_key_pem(pem, password=b"wrong")


def test_export_public_pem_roundtrip():
    kp = generate_keypair()
    pem = export_public_pem(kp)
    assert pem.startswith(b"-----BEGIN PUBLIC KEY-----")
    pk = load_public_key(pem)
    assert pk.public_bytes_raw() == kp.public_key.public_bytes_raw()


def test_load_public_key_from_did_key_string():
    kp = generate_keypair()
    pk = load_public_key(kp.did_key)
    assert pk.public_bytes_raw() == kp.public_key.public_bytes_raw()


def test_load_public_key_from_raw_bytes():
    kp = generate_keypair()
    raw = kp.public_key.public_bytes_raw()
    pk = load_public_key(raw)
    assert pk.public_bytes_raw() == raw


# ── JWS sign + verify ───────────────────────────────────────────────────────


def test_sign_and_verify_dict_payload():
    kp = generate_keypair()
    jws_str = sign({"hello": "world"}, kp.private_key, kid=kp.did_key)
    result = verify(jws_str)
    assert result.valid is True
    assert result.payload == {"hello": "world"}
    assert result.kid == kp.did_key
    assert result.header["alg"] == "EdDSA"
    assert result.header["typ"] == "JWT"


def test_sign_and_verify_string_payload():
    kp = generate_keypair()
    jws_str = sign("plain text body", kp.private_key, kid=kp.did_key)
    result = verify(jws_str)
    assert result.valid is True
    # String payloads are returned as bytes when they don't parse as JSON
    assert result.payload == b"plain text body"


def test_sign_with_typ_arche_jws():
    kp = generate_keypair()
    jws_str = sign({"foo": "bar"}, kp.private_key, kid=kp.did_key, typ="arche+jws")
    result = verify(jws_str)
    assert result.valid is True
    assert result.header["typ"] == "arche+jws"


def test_verify_tampered_payload_fails():
    kp = generate_keypair()
    jws_str = sign({"amount": 100}, kp.private_key, kid=kp.did_key)
    # Splice a different payload in
    header, _, signature = jws_str.split(".")
    import base64
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps({"amount": 1000000}, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode("ascii")
    tampered = f"{header}.{tampered_payload}.{signature}"

    result = verify(tampered)
    assert result.valid is False
    assert "verification failed" in (result.error or "")


def test_verify_wrong_key_fails():
    kp_a = generate_keypair()
    kp_b = generate_keypair()
    jws_str = sign({"x": 1}, kp_a.private_key, kid=kp_a.did_key)
    # Override the kid to B so verify resolves to the wrong key
    result = verify(jws_str, public_key=kp_b.public_key)
    assert result.valid is False
    assert "verification failed" in (result.error or "")


def test_verify_malformed_jws_returns_error_not_exception():
    result = verify("not a real jws")
    assert result.valid is False
    assert "3 JWS segments" in (result.error or "")


def test_verify_unsupported_alg_fails_cleanly():
    """A JWS with alg=HS256 should be rejected (we only support EdDSA)."""
    import base64
    header = base64.urlsafe_b64encode(
        b'{"alg":"HS256","typ":"JWT"}'
    ).rstrip(b"=").decode("ascii")
    payload = base64.urlsafe_b64encode(b'{"x":1}').rstrip(b"=").decode("ascii")
    fake = f"{header}.{payload}.AAAA"
    result = verify(fake)
    assert result.valid is False
    assert "EdDSA" in (result.error or "")


# ── Detached JWS ────────────────────────────────────────────────────────────


def test_detached_jws_roundtrip():
    kp = generate_keypair()
    payload = b"binary attachment bytes \x00\x01\x02"
    jws_str = sign(payload, kp.private_key, kid=kp.did_key, detached=True)
    # Detached form has empty payload segment
    parts = jws_str.split(".")
    assert len(parts) == 3
    assert parts[1] == ""

    result = verify(jws_str, detached_payload=payload)
    assert result.valid is True


def test_detached_jws_without_payload_fails():
    kp = generate_keypair()
    jws_str = sign(b"x", kp.private_key, kid=kp.did_key, detached=True)
    result = verify(jws_str)  # no detached_payload supplied
    assert result.valid is False
    assert "detached_payload" in (result.error or "")


def test_detached_jws_wrong_payload_fails():
    kp = generate_keypair()
    jws_str = sign(b"original", kp.private_key, kid=kp.did_key, detached=True)
    result = verify(jws_str, detached_payload=b"different")
    assert result.valid is False
    assert "verification failed" in (result.error or "")


# ── Determinism & canonicalization ──────────────────────────────────────────


def test_signature_is_deterministic_for_same_payload():
    """Ed25519 is deterministic: same key + same input -> same signature."""
    kp = generate_keypair()
    jws_a = sign({"a": 1, "b": 2}, kp.private_key, kid=kp.did_key)
    jws_b = sign({"a": 1, "b": 2}, kp.private_key, kid=kp.did_key)
    assert jws_a == jws_b


def test_payload_canonicalization_sorts_keys():
    """Dict payloads are JSON-encoded with sort_keys for stability —
    the same dict in different insertion orders must produce the same JWS."""
    kp = generate_keypair()
    jws_a = sign({"b": 2, "a": 1}, kp.private_key, kid=kp.did_key)
    jws_b = sign({"a": 1, "b": 2}, kp.private_key, kid=kp.did_key)
    assert jws_a == jws_b


# ── Offline did:key resolution ──────────────────────────────────────────────


def test_verify_uses_did_key_from_kid_when_no_resolver():
    """The offline path: kid is a did:key, no resolver provided, no
    public_key argument. verify() decodes the did:key directly."""
    kp = generate_keypair()
    jws_str = sign({"offline": True}, kp.private_key, kid=kp.did_key)
    # No public_key, no resolver — should still verify
    result = verify(jws_str)
    assert result.valid is True


def test_verify_with_custom_resolver():
    """Caller can plug in arbitrary kid -> key resolution (e.g., did:web)."""
    kp = generate_keypair()
    # Make up a non-did:key kid
    jws_str = sign({"x": 1}, kp.private_key, kid="did:web:example.org#key-1")

    calls: list[str] = []

    def resolver(kid: str):
        calls.append(kid)
        return kp.public_key

    result = verify(jws_str, resolver=resolver, allow_did_key_from_kid=False)
    assert result.valid is True
    assert calls == ["did:web:example.org#key-1"]


def test_verify_no_key_available_returns_error():
    kp = generate_keypair()
    # Sign with a kid that's not a did:key, and provide no resolver/key
    jws_str = sign({"x": 1}, kp.private_key, kid="custom:identifier")
    result = verify(jws_str, allow_did_key_from_kid=False)
    assert result.valid is False
    assert "No public key" in (result.error or "")
