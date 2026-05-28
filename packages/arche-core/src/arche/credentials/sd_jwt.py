# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""SD-JWT-VC (Selective Disclosure JWT Verifiable Credentials) for arche.

Per the locked verifiability roadmap (2026-06-02): arche emits SD-JWT-VC
as the v0.2 Verifiable Credential format, NOT JSON-LD VC 1.1. This is
the format EUDI Wallet ARF and MOSIP Inji standardize on. JSON-LD VC 1.1
via ``didkit`` is deferred to Stage 3 as the ``arche-core[didkit]`` extra.

What SD-JWT does:

- Wraps a JSON claim set in a JWS (the same JWS our envelope uses).
- For each "selectively disclosable" claim, the issuer puts a SHA-256
  hash of the disclosure in the ``_sd`` array of the JWT body instead
  of the claim's value.
- Each disclosure is a base64url-encoded ``[salt, claim_name, claim_value]``
  tuple, appended to the JWT with ``~`` separators.
- The holder decides which disclosures to forward to the verifier.
- The verifier reconstructs only the disclosed claims by hashing each
  presented disclosure and matching against ``_sd``.

The result: cryptographic non-repudiation of issuer claims + privacy
through holder-controlled disclosure. The verifier sees only what the
holder shared, but every disclosed claim is still signed by the issuer.

Wire format (compact)::

    <JWS_compact>~<disclosure1>~<disclosure2>~...~

Note the trailing ``~`` per the spec. Disclosures may be omitted by
the holder during presentation.

References:
- IETF draft-ietf-oauth-selective-disclosure-jwt-08 and later
- EUDI Wallet ARF v1.4+ SD-JWT-VC profile
- W3C VC Data Model 2.0 (SD-JWT-VC is one of the conforming formats)
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from arche.sign.envelope import ArcheSignedDocument
from arche.sign.jws import _b64url_decode, _b64url_encode, sign, verify
from arche.sign.keys import Keypair, encode_did_key

SD_JWT_TYP = "vc+sd-jwt"
SD_HASH_ALG = "sha-256"


# ---------------------------------------------------------------------------
# Disclosure helpers
# ---------------------------------------------------------------------------

def _make_disclosure(claim_name: str, claim_value: Any) -> tuple[str, str]:
    """Build one SD-JWT disclosure.

    Returns
    -------
    (disclosure, sd_hash)
        ``disclosure`` is the base64url-encoded JSON triple
        ``[salt, claim_name, claim_value]``. ``sd_hash`` is the
        base64url-encoded SHA-256 digest of that disclosure string —
        what goes into the JWT's ``_sd`` array.
    """
    salt = _b64url_encode(secrets.token_bytes(16))
    triple = [salt, claim_name, claim_value]
    disclosure = _b64url_encode(
        json.dumps(triple, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    sd_hash = _b64url_encode(hashlib.sha256(disclosure.encode("ascii")).digest())
    return disclosure, sd_hash


def _parse_disclosure(disclosure: str) -> tuple[str, str, Any]:
    """Decode a disclosure back into (salt, claim_name, claim_value)."""
    decoded = _b64url_decode(disclosure)
    triple = json.loads(decoded)
    if not isinstance(triple, list) or len(triple) != 3:
        raise ValueError(f"Malformed disclosure: expected 3-tuple, got {triple!r}")
    salt, claim_name, claim_value = triple
    return salt, claim_name, claim_value


def _disclosure_hash(disclosure: str) -> str:
    """Compute the ``_sd``-array hash for a disclosure string."""
    return _b64url_encode(hashlib.sha256(disclosure.encode("ascii")).digest())


# ---------------------------------------------------------------------------
# Issue (issuer side)
# ---------------------------------------------------------------------------

@dataclass
class SDJWTResult:
    """The output of ``issue_sd_jwt``.

    ``compact`` is the wire format (``<JWS>~<d1>~<d2>~...~``) ready to be
    transmitted to the holder. ``jws`` is the bare JWS without disclosures.
    ``disclosures`` is the list the holder can choose to forward selectively.
    """

    compact: str
    jws: str
    disclosures: list[str] = field(default_factory=list)


def issue_sd_jwt(
    *,
    claims: dict[str, Any],
    issuer_key: Keypair | Ed25519PrivateKey,
    disclosable_claims: list[str] | None = None,
    issuer_did: str | None = None,
    vc_type: str = "ArcheDetectionCredential",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> SDJWTResult:
    """Issue an SD-JWT-VC.

    Parameters
    ----------
    claims:
        The full claim set. Keys in ``disclosable_claims`` are removed from
        the visible payload and re-emitted as separate disclosures.
    issuer_key:
        A :class:`Keypair` (uses ``did_key`` as kid) or a raw
        ``Ed25519PrivateKey`` (requires ``issuer_did``).
    disclosable_claims:
        Top-level keys to hide behind ``_sd`` hashes. When ``None``, all
        top-level keys are disclosable (full selective disclosure).
    issuer_did:
        Required when ``issuer_key`` is a raw private key.
    vc_type:
        SD-JWT-VC ``vct`` claim. Defaults to ``"ArcheDetectionCredential"``.
    issued_at, expires_at:
        Optional ``iat`` / ``exp`` claims.
    """
    if isinstance(issuer_key, Keypair):
        private_key = issuer_key.private_key
        did = issuer_key.did_key
    elif isinstance(issuer_key, Ed25519PrivateKey):
        private_key = issuer_key
        did = issuer_did or encode_did_key(issuer_key.public_key())
    else:
        raise TypeError(f"Unsupported key type: {type(issuer_key).__name__}")

    # If no whitelist given, every top-level claim is disclosable.
    if disclosable_claims is None:
        disclosable_claims = list(claims.keys())

    # Split claims into "always visible" and "disclosable".
    visible_claims: dict[str, Any] = {}
    sd_hashes: list[str] = []
    disclosures: list[str] = []

    for key, value in claims.items():
        if key in disclosable_claims:
            disc, sd_hash = _make_disclosure(key, value)
            disclosures.append(disc)
            sd_hashes.append(sd_hash)
        else:
            visible_claims[key] = value

    # Standard SD-JWT-VC top-level claims.
    payload: dict[str, Any] = {
        **visible_claims,
        "iss": did,
        "vct": vc_type,
        "_sd_alg": SD_HASH_ALG,
        "_sd": sd_hashes,
    }
    if issued_at:
        payload["iat"] = int(issued_at.timestamp())
    if expires_at:
        payload["exp"] = int(expires_at.timestamp())

    # Sign as a JWS with the SD-JWT-VC typ header.
    jws = sign(payload, private_key, kid=did, typ=SD_JWT_TYP)

    compact = jws + "~" + "~".join(disclosures) + "~"
    return SDJWTResult(compact=compact, jws=jws, disclosures=disclosures)


# ---------------------------------------------------------------------------
# Verify (verifier side)
# ---------------------------------------------------------------------------

@dataclass
class SDJWTVerifyResult:
    """The outcome of verifying an SD-JWT-VC presentation."""

    valid: bool
    issuer_did: str | None
    issuer_kid: str | None
    vc_type: str | None
    disclosed_claims: dict[str, Any] = field(default_factory=dict)
    visible_claims: dict[str, Any] = field(default_factory=dict)
    issued_at: int | None = None
    expires_at: int | None = None
    expired: bool = False
    error: str | None = None

    @property
    def claims(self) -> dict[str, Any]:
        """All claims the verifier can see: visible + disclosed."""
        return {**self.visible_claims, **self.disclosed_claims}


def verify_sd_jwt(
    compact: str,
    *,
    public_key: Ed25519PublicKey | None = None,
    resolver: Callable[[str], Ed25519PublicKey | None] | None = None,
    expected_vc_type: str | None = None,
    check_expiry: bool = True,
    now: datetime | None = None,
) -> SDJWTVerifyResult:
    """Verify an SD-JWT-VC presentation.

    Parameters
    ----------
    compact:
        Wire format ``<JWS>~<disclosure>~...~``.
    public_key, resolver:
        Same as :func:`arche.sign.verify`. Default offline path: decode
        the issuer's ``did:key`` from the JWS ``kid`` header.
    expected_vc_type:
        If provided, the SD-JWT's ``vct`` must match.
    check_expiry:
        Reject expired credentials (``exp`` claim in the past).
    """
    # Split compact form into JWS + disclosures (trailing ~ produces empty
    # element which we drop)
    segments = compact.split("~")
    jws_compact = segments[0]
    presented_disclosures = [s for s in segments[1:] if s]

    # Verify the JWS
    v = verify(jws_compact, public_key=public_key, resolver=resolver)
    if not v.valid:
        return SDJWTVerifyResult(
            valid=False,
            issuer_did=None,
            issuer_kid=v.kid,
            vc_type=None,
            error=v.error,
        )

    if not isinstance(v.payload, dict):
        return SDJWTVerifyResult(
            valid=False, issuer_did=None, issuer_kid=v.kid, vc_type=None,
            error="SD-JWT payload is not a JSON object",
        )

    payload = v.payload

    # SD-JWT type marker
    if v.header.get("typ") not in (SD_JWT_TYP, "JWT"):
        return SDJWTVerifyResult(
            valid=False, issuer_did=payload.get("iss"), issuer_kid=v.kid,
            vc_type=payload.get("vct"),
            error=f"Expected typ={SD_JWT_TYP}, got {v.header.get('typ')!r}",
        )

    sd_alg = payload.get("_sd_alg", SD_HASH_ALG)
    if sd_alg != SD_HASH_ALG:
        return SDJWTVerifyResult(
            valid=False, issuer_did=payload.get("iss"), issuer_kid=v.kid,
            vc_type=payload.get("vct"),
            error=f"Unsupported _sd_alg: {sd_alg!r} (only sha-256 supported)",
        )

    vc_type = payload.get("vct")
    if expected_vc_type and vc_type != expected_vc_type:
        return SDJWTVerifyResult(
            valid=False, issuer_did=payload.get("iss"), issuer_kid=v.kid,
            vc_type=vc_type,
            error=f"vct mismatch: expected {expected_vc_type!r}, got {vc_type!r}",
        )

    # Match presented disclosures against the _sd hashes
    sd_hashes = set(payload.get("_sd") or [])
    disclosed: dict[str, Any] = {}
    rejected: list[str] = []
    for d in presented_disclosures:
        h = _disclosure_hash(d)
        if h not in sd_hashes:
            rejected.append(d)
            continue
        try:
            _salt, claim_name, claim_value = _parse_disclosure(d)
        except ValueError as exc:
            return SDJWTVerifyResult(
                valid=False, issuer_did=payload.get("iss"), issuer_kid=v.kid,
                vc_type=vc_type,
                error=f"Malformed disclosure: {exc}",
            )
        disclosed[claim_name] = claim_value

    if rejected:
        return SDJWTVerifyResult(
            valid=False, issuer_did=payload.get("iss"), issuer_kid=v.kid,
            vc_type=vc_type,
            error=(
                f"{len(rejected)} disclosure(s) did not match _sd hashes — "
                "possible tampering or wrong credential"
            ),
        )

    # Visible (non-disclosable) claims = payload minus SD-JWT machinery
    visible = {
        k: v_ for k, v_ in payload.items()
        if k not in {"_sd", "_sd_alg", "iat", "exp"}
    }

    iat = payload.get("iat")
    exp = payload.get("exp")
    expired = False
    if check_expiry and exp is not None:
        when = now or datetime.now(timezone.utc)
        if when.timestamp() > exp:
            expired = True
            return SDJWTVerifyResult(
                valid=False, issuer_did=payload.get("iss"), issuer_kid=v.kid,
                vc_type=vc_type, disclosed_claims=disclosed, visible_claims=visible,
                issued_at=iat, expires_at=exp, expired=True,
                error=f"Credential expired at {exp} (unix ts)",
            )

    return SDJWTVerifyResult(
        valid=True,
        issuer_did=payload.get("iss"),
        issuer_kid=v.kid,
        vc_type=vc_type,
        disclosed_claims=disclosed,
        visible_claims=visible,
        issued_at=iat,
        expires_at=exp,
        expired=expired,
    )


# ---------------------------------------------------------------------------
# Selective presentation (holder side)
# ---------------------------------------------------------------------------

def present(
    compact: str,
    *,
    disclose: list[str] | None = None,
) -> str:
    """Holder-side: build a presentation by selecting which disclosures to forward.

    Parameters
    ----------
    compact:
        The issued SD-JWT-VC (``<JWS>~<d1>~<d2>~...~``).
    disclose:
        Claim names to include in the presentation. If ``None``, all
        original disclosures are forwarded.
    """
    segments = compact.split("~")
    jws_compact = segments[0]
    all_disclosures = [s for s in segments[1:] if s]

    if disclose is None:
        kept = all_disclosures
    else:
        kept = []
        for d in all_disclosures:
            try:
                _salt, claim_name, _value = _parse_disclosure(d)
            except ValueError:
                continue
            if claim_name in disclose:
                kept.append(d)

    return jws_compact + "~" + "~".join(kept) + "~"


# ---------------------------------------------------------------------------
# Convenience: re-frame an ArcheSignedDocument as an SD-JWT-VC
# ---------------------------------------------------------------------------

def envelope_to_sd_jwt(
    envelope: ArcheSignedDocument,
    *,
    issuer_key: Keypair | Ed25519PrivateKey,
    issuer_did: str | None = None,
    disclosable_keys: list[str] | None = None,
    vc_type: str = "ArcheDetectionCredential",
) -> SDJWTResult:
    """Take an existing :class:`ArcheSignedDocument` and emit it as
    SD-JWT-VC.

    The envelope already carries the full Pipeline.Result. SD-JWT-VC
    adds selective disclosure on top: the holder can show some
    detection categories or policy outcomes while hiding others, with
    the issuer's signature still binding the whole.

    Defaults: all envelope fields except ``schema_version`` and
    ``issuer`` are selectively disclosable.
    """
    claims = envelope.to_dict()
    if disclosable_keys is None:
        # By default, hide the policy outcomes + detections + redacted
        # text — these are the privacy-sensitive bits the holder may
        # want to selectively show.
        disclosable_keys = [
            "detections", "policy_outcomes", "addresses",
            "redacted_text", "doc_hash", "purpose", "jurisdiction",
        ]

    issued_at = None
    if envelope.issued_at:
        try:
            issued_at = datetime.fromisoformat(envelope.issued_at)
        except ValueError:
            pass

    expires_at = None
    if envelope.expires_at:
        try:
            expires_at = datetime.fromisoformat(envelope.expires_at)
        except ValueError:
            pass

    return issue_sd_jwt(
        claims=claims,
        issuer_key=issuer_key,
        disclosable_claims=disclosable_keys,
        issuer_did=issuer_did,
        vc_type=vc_type,
        issued_at=issued_at,
        expires_at=expires_at,
    )


__all__ = [
    "SDJWTResult",
    "SDJWTVerifyResult",
    "issue_sd_jwt",
    "verify_sd_jwt",
    "present",
    "envelope_to_sd_jwt",
    "SD_JWT_TYP",
]
