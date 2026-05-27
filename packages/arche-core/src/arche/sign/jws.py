# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Hand-rolled JWS compact serialization (RFC 7515) for arche.sign.

Per the verifiability roadmap locked decision: zero new base dependencies.
A full JOSE library (joserfc / pyjwt) would add a transitive surface that
arche-core doesn't need. The compact JWS format is small enough to
implement directly over `cryptography` in ~80 lines and stays under our
test discipline.

What we support:

- ``alg: EdDSA`` (Ed25519). This is the v0.2 default.
- Compact serialization (``base64url(header).base64url(payload).base64url(sig)``).
- The ``kid`` header carrying the issuer's ``did:key``.
- Detached signatures (``base64url(header)..base64url(sig)``) for cases
  where the payload is already transmitted elsewhere (e.g., a signed
  attached file).

What we don't support (yet):

- JWS JSON serialization (we ship compact only — the streamable form
  used by EUDI Wallet, MOSIP e-signet, and SD-JWT-VC).
- Other algorithms. ECDSA/RSA-PSS land via opt-in extras in Stage 2.
- Header parameters beyond ``alg``, ``typ``, and ``kid``.

The verifier resolves the ``kid`` to a public key by the caller-provided
``resolver`` function, or by extracting an embedded did:key directly
when the ``kid`` is a did:key string.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from arche.sign.keys import decode_did_key


# ---------------------------------------------------------------------------
# Base64url helpers (no padding, per RFC 7515 §2)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    """Base64url-encode bytes, stripping padding (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    """Base64url-decode a string, re-adding padding."""
    padding = (-len(text)) % 4
    return base64.urlsafe_b64decode(text + ("=" * padding))


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """Outcome of verifying a JWS.

    Attributes
    ----------
    valid:
        True iff the signature verified against the resolved key.
    header:
        The parsed protected header (``alg``, ``typ``, ``kid``, ...).
    payload:
        The JSON-decoded payload (or raw bytes if not JSON).
    kid:
        Convenience: the ``kid`` header, often a did:key.
    error:
        Human-readable reason for failure, ``None`` on success.
    """

    valid: bool
    header: dict[str, Any]
    payload: Any
    kid: str | None
    error: str | None = None


# ---------------------------------------------------------------------------
# Sign
# ---------------------------------------------------------------------------

def sign(
    payload: bytes | str | dict,
    private_key: Ed25519PrivateKey,
    *,
    kid: str | None = None,
    typ: str = "JWT",
    detached: bool = False,
    extra_header: dict[str, Any] | None = None,
) -> str:
    """Sign a payload as a JWS in compact serialization.

    Parameters
    ----------
    payload:
        Either bytes (treated as opaque), str (UTF-8 encoded), or a dict
        (JSON-encoded with sort_keys for stability).
    private_key:
        Ed25519 private key from ``cryptography``.
    kid:
        Optional key identifier; typically the issuer's did:key. Embedded
        in the protected header so verifiers know which key to use.
    typ:
        ``typ`` header. Default ``"JWT"`` for JOSE-compatible consumers;
        use ``"arche+jws"`` for arche envelopes.
    detached:
        If True, return the compact form with an empty payload segment
        (``b64url(header)..b64url(sig)``). The verifier must supply the
        payload separately.
    extra_header:
        Additional header parameters to include.

    Returns
    -------
    str
        Compact JWS string ``header.payload.signature`` (or
        ``header..signature`` if detached).
    """
    header: dict[str, Any] = {"alg": "EdDSA", "typ": typ}
    if kid is not None:
        header["kid"] = kid
    if extra_header:
        header.update(extra_header)
    header_b = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")

    if isinstance(payload, dict):
        payload_b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        payload_b = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        payload_b = bytes(payload)
    else:
        raise TypeError(f"Unsupported payload type: {type(payload).__name__}")

    enc_header = _b64url_encode(header_b)
    enc_payload = _b64url_encode(payload_b)
    signing_input = f"{enc_header}.{enc_payload}".encode("ascii")
    signature = private_key.sign(signing_input)
    enc_signature = _b64url_encode(signature)

    if detached:
        return f"{enc_header}..{enc_signature}"
    return f"{enc_header}.{enc_payload}.{enc_signature}"


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify(
    jws_compact: str,
    *,
    public_key: Ed25519PublicKey | None = None,
    resolver: Callable[[str], Ed25519PublicKey | None] | None = None,
    detached_payload: bytes | str | None = None,
    allow_did_key_from_kid: bool = True,
) -> VerificationResult:
    """Verify a JWS compact-form signature.

    Parameters
    ----------
    jws_compact:
        The compact JWS string.
    public_key:
        Public key for verification, if known out-of-band. If omitted,
        the verifier tries ``resolver(kid)`` then falls back to decoding
        the ``kid`` as a did:key (when ``allow_did_key_from_kid=True``).
    resolver:
        Optional function mapping a ``kid`` (e.g. did:web URL) to an
        Ed25519 public key. Lets callers plug in arbitrary key discovery.
    detached_payload:
        For detached JWS verification: the original payload bytes/string.
    allow_did_key_from_kid:
        When True (default), if no public_key or resolver-resolved key
        is available, treat the ``kid`` as a did:key and decode the
        public key directly from it. This is the offline-friendly path.
    """
    parts = jws_compact.split(".")
    if len(parts) != 3:
        return VerificationResult(
            valid=False, header={}, payload=None, kid=None,
            error=f"Expected 3 JWS segments, got {len(parts)}",
        )
    enc_header, enc_payload, enc_signature = parts

    try:
        header_b = _b64url_decode(enc_header)
        header = json.loads(header_b)
    except (ValueError, json.JSONDecodeError) as exc:
        return VerificationResult(
            valid=False, header={}, payload=None, kid=None,
            error=f"Header parse failed: {exc}",
        )

    if header.get("alg") != "EdDSA":
        return VerificationResult(
            valid=False, header=header, payload=None, kid=header.get("kid"),
            error=f"Unsupported alg: {header.get('alg')!r}; expected EdDSA",
        )

    # Reconstruct signing input
    if enc_payload == "":
        # Detached form
        if detached_payload is None:
            return VerificationResult(
                valid=False, header=header, payload=None, kid=header.get("kid"),
                error="Detached JWS but no detached_payload supplied",
            )
        if isinstance(detached_payload, str):
            payload_b = detached_payload.encode("utf-8")
        else:
            payload_b = bytes(detached_payload)
        enc_payload_for_sig = _b64url_encode(payload_b)
    else:
        try:
            payload_b = _b64url_decode(enc_payload)
        except ValueError as exc:
            return VerificationResult(
                valid=False, header=header, payload=None, kid=header.get("kid"),
                error=f"Payload decode failed: {exc}",
            )
        enc_payload_for_sig = enc_payload

    signing_input = f"{enc_header}.{enc_payload_for_sig}".encode("ascii")

    try:
        signature = _b64url_decode(enc_signature)
    except ValueError as exc:
        return VerificationResult(
            valid=False, header=header, payload=None, kid=header.get("kid"),
            error=f"Signature decode failed: {exc}",
        )

    # Resolve public key
    kid = header.get("kid")
    pk = public_key
    if pk is None and resolver is not None and kid is not None:
        pk = resolver(kid)
    if pk is None and allow_did_key_from_kid and isinstance(kid, str) and kid.startswith("did:key:"):
        try:
            pk = decode_did_key(kid)
        except ValueError as exc:
            return VerificationResult(
                valid=False, header=header, payload=None, kid=kid,
                error=f"did:key decode failed: {exc}",
            )
    if pk is None:
        return VerificationResult(
            valid=False, header=header, payload=None, kid=kid,
            error="No public key available (provide public_key or resolver, or set kid to did:key)",
        )

    try:
        pk.verify(signature, signing_input)
    except InvalidSignature:
        return VerificationResult(
            valid=False, header=header, payload=None, kid=kid,
            error="Ed25519 signature verification failed",
        )

    # Parse payload as JSON when reasonable; fall back to bytes
    try:
        payload: Any = json.loads(payload_b)
    except (ValueError, json.JSONDecodeError):
        payload = payload_b

    return VerificationResult(valid=True, header=header, payload=payload, kid=kid)
