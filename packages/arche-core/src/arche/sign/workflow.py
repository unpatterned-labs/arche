# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""High-level sign-share-extract workflows.

This module ships the two reference workflows the user's stated vision
turns on:

- :class:`SignWorkflow` — issuer side. Run a document through
  :class:`arche.workflow.Pipeline` for the configured jurisdiction,
  then wrap the result in a signed ``ArcheSignedDocument`` envelope.

- :class:`VerifyExtractWorkflow` — recipient side. Take a signed
  envelope, verify the signature offline (via embedded ``did:key`` or
  caller-provided resolver), and return a structured result with the
  recovered detections, policy outcomes, and redacted text.

The classes are deliberately small. The heavy lifting is in
:mod:`arche.workflow._primitive` (detection + policy) and
:mod:`arche.sign.jws` (signing + verification). These workflows are the
composition layer that makes "sign a document and share it" a one-line
call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from arche.sign.envelope import ArcheSignedDocument
from arche.sign.jws import VerificationResult, sign, verify
from arche.sign.keys import Keypair, encode_did_key
from arche.workflow._primitive import Pipeline, Result


# ---------------------------------------------------------------------------
# SignWorkflow — issuer side
# ---------------------------------------------------------------------------

class SignWorkflow:
    """Compose Pipeline + signing into a single ``sign(text, key)`` call.

    The issuer constructs a workflow for one jurisdiction, then signs
    arbitrary documents under that jurisdiction's statute. The output
    is a JWS-compact string carrying the canonical envelope.

    Examples
    --------
    >>> from arche.sign import SignWorkflow, generate_keypair
    >>> kp = generate_keypair()
    >>> wf = SignWorkflow(jurisdiction="NG", statute="NDPA-2023",
    ...                   tokenize_salt="org_a")
    >>> jws = wf.sign("Adesola Okonkwo, NIN 12345678901.", kp,
    ...               purpose="dsar_response")
    >>> jws.startswith("eyJ")  # base64url-encoded JOSE header
    True
    """

    def __init__(
        self,
        jurisdiction: str | None = None,
        statute: str | None = None,
        detectors: list[str] | None = None,
        tokenize_salt: str = "",
        pipeline: Pipeline | None = None,
    ):
        """Configure the workflow.

        Parameters
        ----------
        jurisdiction:
            ISO 3166-1 alpha-2 code. Drives per-country detector
            selection and statute auto-discovery.
        statute:
            Statute identifier (e.g. ``"NDPA-2023"``). When omitted,
            inferred from ``jurisdiction``.
        detectors:
            Detector packages to run. Passed through to ``Pipeline``.
        tokenize_salt:
            Per-issuer salt for deterministic tokenization. Should be
            stable for an issuer across signings so identical inputs
            tokenize identically.
        pipeline:
            Inject a custom Pipeline instance instead of constructing
            one. Useful for testing or sharing a pre-warmed pipeline.
        """
        if pipeline is not None:
            self.pipeline = pipeline
        else:
            self.pipeline = Pipeline(
                jurisdiction=jurisdiction,
                statute=statute,
                detectors=detectors,
                audit=False,  # audit log stays out of the signed envelope
                tokenize_salt=tokenize_salt,
            )
        self.tokenize_salt = tokenize_salt

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def sign(
        self,
        text: str,
        key: Keypair | Ed25519PrivateKey,
        *,
        purpose: str = "",
        expires_at: datetime | None = None,
        issuer_did: str | None = None,
    ) -> str:
        """Run the pipeline and emit a JWS-signed envelope.

        Parameters
        ----------
        text:
            Document text to process.
        key:
            Either a :class:`Keypair` (uses ``key.did_key`` automatically)
            or a raw ``Ed25519PrivateKey`` (requires ``issuer_did`` or
            the key won't be addressable on the verify side).
        purpose:
            Free-form intent string: ``"dsar_response"``, ``"kyb_attestation"``,
            ``"audit_export"``, etc.
        expires_at:
            Optional UTC datetime after which the envelope is stale.
        issuer_did:
            Required when ``key`` is a raw private key. Ignored when
            ``key`` is a :class:`Keypair` (we use ``key.did_key``).

        Returns
        -------
        str
            JWS compact serialization carrying the envelope.
        """
        private_key, did = _resolve_signer(key, issuer_did)

        # 1. Run the pipeline (detection + policy)
        result: Result = self.pipeline.process(text)

        # 2. Build the envelope
        envelope = ArcheSignedDocument.from_pipeline_result(
            result,
            issuer_did=did,
            purpose=purpose,
            expires_at=expires_at,
        )

        # 3. Sign the envelope as a JWS
        return sign(
            envelope.to_dict(),
            private_key,
            kid=did,
            typ="arche+jws",
        )

    def describe(self) -> dict[str, Any]:
        """Describe what this workflow will do (PRD FR-WF-8)."""
        return {
            "kind": "SignWorkflow",
            **self.pipeline.describe(),
            "envelope_schema": "arche+envelope/v1",
            "signature_alg": "EdDSA",
            "tokenize_salt_set": bool(self.tokenize_salt),
        }


# ---------------------------------------------------------------------------
# VerifyExtractWorkflow — recipient side
# ---------------------------------------------------------------------------

@dataclass
class VerifyExtractResult:
    """The recipient's view of a signed document.

    On a valid signature, this carries the recovered envelope plus
    metadata describing the verification context.
    """

    signature_valid: bool
    envelope: ArcheSignedDocument | None
    issuer_did: str | None
    issued_at: str | None
    statute_at_signing: str | None
    schema_version: str | None
    expired: bool = False
    header: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    # Convenience accessors that mirror Pipeline.Result
    @property
    def detections(self) -> list[dict[str, Any]]:
        return self.envelope.detections if self.envelope else []

    @property
    def policy_outcomes(self) -> list[dict[str, Any]]:
        return self.envelope.policy_outcomes if self.envelope else []

    @property
    def redacted_text(self) -> str:
        return self.envelope.redacted_text if self.envelope else ""

    @property
    def doc_hash(self) -> str:
        return self.envelope.doc_hash if self.envelope else ""

    @property
    def jurisdiction(self) -> str | None:
        return self.envelope.jurisdiction if self.envelope else None


class VerifyExtractWorkflow:
    """Verify a signed envelope and recover the structured Result.

    The default offline path: the JWS ``kid`` header carries a
    ``did:key``, the verifier decodes the public key directly, no
    infrastructure required.

    Examples
    --------
    >>> from arche.sign import VerifyExtractWorkflow
    >>> wf = VerifyExtractWorkflow()
    >>> r = wf.process(signed_jws_string)
    >>> r.signature_valid
    True
    >>> r.redacted_text
    'Adesola Okonkwo, NIN [NIN].'
    """

    def __init__(
        self,
        *,
        public_key: Ed25519PublicKey | None = None,
        resolver: Callable[[str], Ed25519PublicKey | None] | None = None,
        strict: bool = True,
        require_purpose: str | None = None,
        require_jurisdiction: str | None = None,
        check_expiry: bool = True,
    ):
        """Configure verification policy.

        Parameters
        ----------
        public_key:
            Pre-known public key. If provided, the JWS ``kid`` is
            ignored for resolution (signature must still match).
        resolver:
            Custom ``kid -> public_key`` resolver (e.g., did:web).
        strict:
            When True, ``process()`` raises ``SignatureVerificationError``
            on any failure. When False, returns a ``VerifyExtractResult``
            with ``signature_valid=False`` instead.
        require_purpose:
            Reject envelopes whose ``purpose`` field doesn't match.
        require_jurisdiction:
            Reject envelopes whose ``jurisdiction`` field doesn't match.
        check_expiry:
            Reject envelopes whose ``expires_at`` is in the past.
        """
        self.public_key = public_key
        self.resolver = resolver
        self.strict = strict
        self.require_purpose = require_purpose
        self.require_jurisdiction = require_jurisdiction
        self.check_expiry = check_expiry

    def process(self, jws_compact: str) -> VerifyExtractResult:
        """Verify a JWS and extract the envelope."""
        v: VerificationResult = verify(
            jws_compact,
            public_key=self.public_key,
            resolver=self.resolver,
        )

        if not v.valid:
            return self._fail(
                error=v.error or "signature invalid",
                header=v.header,
                kid=v.kid,
            )

        # Payload must be a dict for ArcheSignedDocument
        if not isinstance(v.payload, dict):
            return self._fail(
                error=f"Payload is not a JSON object (got {type(v.payload).__name__})",
                header=v.header,
                kid=v.kid,
            )

        envelope = ArcheSignedDocument.from_dict(v.payload)

        # Expiry check
        expired = self.check_expiry and envelope.is_expired()
        if expired:
            return self._fail(
                error=f"Envelope expired at {envelope.expires_at}",
                header=v.header,
                kid=v.kid,
                envelope=envelope,
                expired=True,
            )

        # Purpose check
        if self.require_purpose and envelope.purpose != self.require_purpose:
            return self._fail(
                error=(
                    f"Purpose mismatch: required {self.require_purpose!r}, "
                    f"envelope has {envelope.purpose!r}"
                ),
                header=v.header,
                kid=v.kid,
                envelope=envelope,
            )

        # Jurisdiction check
        if (
            self.require_jurisdiction
            and envelope.jurisdiction != self.require_jurisdiction
        ):
            return self._fail(
                error=(
                    f"Jurisdiction mismatch: required {self.require_jurisdiction!r}, "
                    f"envelope has {envelope.jurisdiction!r}"
                ),
                header=v.header,
                kid=v.kid,
                envelope=envelope,
            )

        return VerifyExtractResult(
            signature_valid=True,
            envelope=envelope,
            issuer_did=envelope.issuer or v.kid,
            issued_at=envelope.issued_at,
            statute_at_signing=envelope.statute,
            schema_version=envelope.schema_version,
            expired=False,
            header=v.header,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _fail(
        self,
        *,
        error: str,
        header: dict[str, Any],
        kid: str | None,
        envelope: ArcheSignedDocument | None = None,
        expired: bool = False,
    ) -> VerifyExtractResult:
        result = VerifyExtractResult(
            signature_valid=False,
            envelope=envelope,
            issuer_did=envelope.issuer if envelope else kid,
            issued_at=envelope.issued_at if envelope else None,
            statute_at_signing=envelope.statute if envelope else None,
            schema_version=envelope.schema_version if envelope else None,
            expired=expired,
            header=header,
            error=error,
        )
        if self.strict:
            raise SignatureVerificationError(error, result)
        return result


class SignatureVerificationError(Exception):
    """Raised by :meth:`VerifyExtractWorkflow.process` when ``strict=True``
    and verification fails."""

    def __init__(self, message: str, result: VerifyExtractResult):
        super().__init__(message)
        self.result = result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_signer(
    key: Keypair | Ed25519PrivateKey,
    issuer_did: str | None,
) -> tuple[Ed25519PrivateKey, str]:
    """Normalize the signing input to (private_key, did) pair."""
    if isinstance(key, Keypair):
        return key.private_key, key.did_key
    if isinstance(key, Ed25519PrivateKey):
        did = issuer_did or encode_did_key(key.public_key())
        return key, did
    raise TypeError(
        f"Expected Keypair or Ed25519PrivateKey, got {type(key).__name__}"
    )
