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

    # Verify offline (kid embeds the did:key, no resolver needed).
    result = verify(jws)
    assert result.valid
    assert result.payload == {"hello": "world"}

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
