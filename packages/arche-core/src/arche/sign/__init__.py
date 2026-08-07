# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche.sign — Ed25519 signatures + did:key + JWS envelope.

Per the verifiability roadmap (locked 2026-06-02): the substrate for the
sign-share-extract identity workflow. Party A signs a document and its
policy-applied detection set; Party B verifies and extracts identity
claims.

Public API::

    from arche.sign import (
        generate_keypair,
        load_private_key_pem,
        load_public_key,
        encode_did_key,
        decode_did_key,
        sign,
        verify,
        Keypair,
        VerificationResult,
    )

    # Generate a fresh keypair (caller-held; arche never stores keys).
    kp = generate_keypair()
    print(kp.did_key)            # "did:key:z6Mk..."

    # Sign an arbitrary payload (dict, str, or bytes).
    jws = sign(
        {"hello": "world"},
        kp.private_key,
        kid=kp.did_key,
        typ="arche+jws",
    )

    # Verify against a key you already trust. Always pass one when the
    # signature is meant to prove *who* signed.
    result = verify(jws, public_key=kp.public_key)
    assert result.valid
    assert result.payload == {"hello": "world"}

.. warning:: Trust comes from the key, not from ``valid``

   ``verify()`` requires a key you already trust. Without ``public_key`` or
   a ``resolver`` it now fails with an actionable error rather than falling
   back to the key the token names for itself.

   That fallback is still available as ``allow_did_key_from_kid=True``, and
   it is genuinely useful for checking an envelope's integrity offline. But
   it authenticates nothing: an attacker can sign any payload with their own
   keypair and set a matching ``kid``, and it will verify. Results from that
   path carry ``key_source="self-asserted"`` and ``trusted=False``.

   **Check ``result.trusted`` whenever the signature is meant to prove who
   signed.** ``valid`` answers "does this signature match this key"; only
   ``trusted`` answers "and did that key come from somewhere I control".

The default algorithm is Ed25519 with did:key issuer identification — the
EUDI Wallet / MOSIP e-signet / DIF reference choice for 2026 DPI work.
ECDSA P-256 and RSA-PSS are Stage 2 opt-in extras for FIPS / legacy PKI
interop. Hybrid PQC (Ed25519 + ML-DSA per NIST FIPS 204) is Stage 2 via
``arche-core[pqc]``.

The high-level :class:`SignWorkflow` and :class:`VerifyExtractWorkflow`
build on these primitives — see ``arche.sign.workflow`` (Day 18).
"""

from arche.sign.envelope import ENVELOPE_SCHEMA_VERSION, ArcheSignedDocument, document_hash
from arche.sign.jws import VerificationResult, sign, verify
from arche.sign.keys import (
    Keypair,
    decode_did_key,
    encode_did_key,
    export_private_pem,
    export_public_pem,
    generate_keypair,
    load_private_key_pem,
    load_public_key,
    save_private_key,
)
from arche.sign.workflow import (
    SignatureVerificationError,
    SignWorkflow,
    VerifyExtractResult,
    VerifyExtractWorkflow,
)

__all__ = [
    # keys
    "Keypair",
    "generate_keypair",
    "load_private_key_pem",
    "load_public_key",
    "encode_did_key",
    "decode_did_key",
    "export_private_pem",
    "export_public_pem",
    "save_private_key",
    # signing primitives
    "sign",
    "verify",
    "VerificationResult",
    # envelope
    "ArcheSignedDocument",
    "ENVELOPE_SCHEMA_VERSION",
    "document_hash",
    # high-level workflows
    "SignWorkflow",
    "VerifyExtractWorkflow",
    "VerifyExtractResult",
    "SignatureVerificationError",
]
