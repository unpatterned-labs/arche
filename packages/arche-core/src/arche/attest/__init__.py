# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Signed attestations of co-reference decisions.

An :class:`Attestation` carries **no raw attribute values** — only the decision,
*numeric* evidence (sims, bits, gate / veto booleans), and content-addressed ids.
It is safe to share openly **when the decision was produced with an
``issuer_key``**: that keys ``reference_id`` / ``decision_id`` so the PII-derived
ids cannot be brute-forced back to the source records. Without an issuer key the
ids are keyless — reproducible locally, but *pseudonymous personal data* (treat
under NDPA/POPIA), not "PII-free".

Two signing modes over the same object:
* ``mode="jws"`` — the whole attestation under one Ed25519 signature; tamper-
  evident and (for a same-entity/deterministic decision) reproducible.
* ``mode="sd-jwt"`` — opted-in subject PII becomes **selectively disclosable**
  claims (salted ``_sd`` digests, IETF SD-JWT-VC), masked until the holder
  discloses them. ``reproducible`` is recorded so a verifier can tell a
  reproducible decision from a graded one. Pass ``holder_key=`` to **bind** the
  credential to a holder (``cnf``): the holder then proves possession with a
  KB-JWT at presentation (:func:`present_attestation`), which the verifier checks
  against a fresh ``aud`` + ``nonce`` — the replay-proof path. An *unbound*
  PII-bearing SD-JWT is a bearer token, so ``include_subject`` requires **either**
  a ``holder_key`` **or** an ``expires_at``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from arche.canonical import is_pii_attribute
from arche.credentials.sd_jwt import issue_sd_jwt, verify_sd_jwt
from arche.sign.jws import sign, verify
from arche.sign.keys import Keypair

if TYPE_CHECKING:
    from arche.resolve.coreference import CoReferenceDecision

_ATT_TYP = "arche+attestation"
_VC_TYPE = "ArcheCoReferenceCredential"
_SCHEMA = "arche+resolution/v1"


@dataclass
class Attestation:
    """The canonical, no-raw-PII, signable form of a decision.

    Carries no raw attribute values; it is *PII-safe to share* only when the
    decision was keyed (ids are HMAC pseudonyms). ``attest`` enforces this.
    """

    decision: str            # identity: same_entity | review | different
    action: str              # merge | hold | no_op
    basis: str
    decision_id: str
    entity_id: str | None
    reference_id_a: str
    reference_id_b: str
    score: float
    factors: dict[str, float]
    field_weights: dict[str, dict[str, float]]
    explanation: str
    gate: dict[str, Any]
    vetoes: dict[str, Any]
    jurisdiction: str
    pins: dict[str, Any]
    reproducible: bool
    purpose: str = "coreference"
    schema_version: str = _SCHEMA
    issuer: str = ""
    issued_at: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """The claim set. ``None`` timestamps are dropped so an untimestamped
        attestation of a reproducible decision serialises to stable bytes."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_decision(
        cls,
        decision: CoReferenceDecision,
        *,
        issuer: str = "",
        purpose: str = "coreference",
        reproducible: bool = True,
        issued_at: str | None = None,
        expires_at: str | None = None,
    ) -> Attestation:
        return cls(
            decision=decision.identity,
            action=decision.action,
            basis=decision.basis,
            decision_id=decision.decision_id,
            entity_id=decision.entity_id,
            reference_id_a=decision.reference_id_a,
            reference_id_b=decision.reference_id_b,
            score=decision.score,
            factors=decision.factors,
            field_weights=decision.field_weights,
            explanation=decision.explanation,
            gate=decision.gate,
            vetoes=decision.vetoes,
            jurisdiction=decision.jurisdiction,
            pins=decision.pins,
            reproducible=reproducible,
            purpose=purpose,
            issuer=issuer,
            issued_at=issued_at,
            expires_at=expires_at,
        )


@dataclass
class SignedAttestation:
    """A signed attestation in compact form + the attestation it wraps."""

    mode: str                 # "jws" | "sd-jwt"
    compact: str
    attestation: Attestation
    disclosures: list[str] = field(default_factory=list)


@dataclass
class AttestationVerifyResult:
    valid: bool
    mode: str
    claims: dict[str, Any]
    decision_id: str | None = None
    reproducible: bool = False
    key_bound: bool = False
    holder_did: str | None = None
    error: str | None = None


def _subject_claims(
    decision: CoReferenceDecision, include_subject: bool | list[str]
) -> dict[str, str]:
    """Flat, disclosable subject PII drawn from reference A (the resolved person).

    ``include_subject=True`` exposes every PII attribute; a list restricts to the
    named ones. Kept flat (``full_name``, ``national_id``) because SD-JWT
    disclosures are top-level.
    """
    wanted = None if include_subject is True else {n.lower() for n in include_subject}
    claims: dict[str, str] = {}
    for attr in decision.reference_a.attributes:
        if getattr(attr, "restricted", False):
            # Two-boundary rule: a statute-`drop`ped value was usable for
            # matching but is NEVER disclosable — no flag can include it.
            continue
        if not is_pii_attribute(attr.name):
            continue
        if wanted is not None and attr.name.lower() not in wanted:
            continue
        claims[attr.name] = attr.value
    return claims


def attest(
    decision: CoReferenceDecision,
    key: Keypair,
    *,
    mode: str = "jws",
    include_subject: bool | list[str] = False,
    issuer_did: str | None = None,
    purpose: str = "coreference",
    issued_at: str | None = None,
    expires_at: datetime | None = None,
    allow_unkeyed: bool = False,
    holder_key: Keypair | None = None,
) -> SignedAttestation:
    """Sign a co-reference decision.

    PII-free by default (``include_subject=False``). Subject PII may be included
    only in ``mode="sd-jwt"``, where it becomes selectively disclosable — never in
    cleartext in a JWS. Because an unbound PII-bearing SD-JWT is a replayable
    bearer token, ``include_subject`` requires **either** a ``holder_key`` (binds
    it, replay-proof) **or** an ``expires_at`` (time-boxes it).

    Refuses to sign a **keyless** decision (one produced without an
    ``issuer_key``): its ``reference_id`` / ``decision_id`` are plain hashes of the
    person's attributes and are brute-forceable back to the source records, so the
    signed artifact would not be PII-free. Produce the decision with an issuer key,
    or pass ``allow_unkeyed=True`` to sign a **local, non-shareable** attestation.
    """
    if not allow_unkeyed and ":sha256:" in decision.decision_id:
        raise ValueError(
            "refusing to attest a keyless decision: its reference_id/decision_id are "
            "sha256 hashes of the person's attributes and can be brute-forced back to "
            "the source records, so the signed artifact would NOT be PII-free. Produce "
            "the decision with an issuer key — coref_references(..., issuer_key=<>=32 "
            "bytes>) — or pass allow_unkeyed=True to sign a LOCAL, non-shareable one."
        )
    issuer = issuer_did or key.did_key
    exp_str = expires_at.isoformat() if expires_at is not None else None
    att = Attestation.from_decision(
        decision, issuer=issuer, purpose=purpose,
        reproducible=(mode == "jws"), issued_at=issued_at, expires_at=exp_str,
    )

    if mode == "jws":
        if include_subject:
            raise ValueError(
                "include_subject requires mode='sd-jwt' — PII must be selectively "
                "disclosable, never cleartext in a JWS."
            )
        compact = sign(att.to_dict(), key.private_key, kid=key.did_key, typ=_ATT_TYP)
        return SignedAttestation(mode="jws", compact=compact, attestation=att)

    if mode == "sd-jwt":
        if include_subject and expires_at is None and holder_key is None:
            raise ValueError(
                "include_subject requires expires_at OR holder_key — an unbound "
                "PII-bearing SD-JWT is a replayable bearer credential; either set an "
                "expiry, or bind it to a holder key (holder_key=) so a KB-JWT is "
                "required at presentation (the stronger, replay-proof option)."
            )
        claims = att.to_dict()
        disclosable: list[str] = []
        if include_subject:
            subject = _subject_claims(decision, include_subject)
            claims.update(subject)
            disclosable = list(subject.keys())
        result = issue_sd_jwt(
            claims=claims,
            issuer_key=key,
            disclosable_claims=disclosable,
            issuer_did=issuer_did,
            vc_type=_VC_TYPE,
            expires_at=expires_at,
            holder_key=holder_key,
        )
        return SignedAttestation(
            mode="sd-jwt", compact=result.compact, attestation=att,
            disclosures=list(result.disclosures),
        )

    raise ValueError(f"unknown attest mode {mode!r}; use 'jws' or 'sd-jwt'")


def present_attestation(
    signed: SignedAttestation,
    *,
    disclose: list[str] | None = None,
    holder_key: Keypair,
    aud: str,
    nonce: str,
) -> str:
    """Holder-side: build a key-bound presentation of an SD-JWT attestation.

    Discloses only ``disclose`` and appends a KB-JWT proving possession of the
    holder key, bound to the verifier's ``aud`` + fresh ``nonce`` so the verifier
    can reject a replayed presentation. Requires the attestation to have been
    issued with the matching ``holder_key`` (see :func:`attest`).
    """
    if signed.mode != "sd-jwt":
        raise ValueError("only sd-jwt attestations can be presented")
    from arche.credentials.sd_jwt import present

    return present(
        signed.compact, disclose=disclose, holder_key=holder_key, aud=aud, nonce=nonce
    )


def verify_attestation(
    compact: str,
    *,
    public_key: Any = None,
    resolver: Any = None,
    require_key_binding: bool = False,
    expected_aud: str | None = None,
    expected_nonce: str | None = None,
) -> AttestationVerifyResult:
    """Verify a signed attestation (auto-detects JWS vs SD-JWT-VC).

    For a key-bound SD-JWT presentation, pass ``require_key_binding=True`` plus
    the ``expected_aud`` and the fresh ``expected_nonce`` you challenged the
    holder with; the KB-JWT is then verified against the credential's ``cnf`` and
    rejected on any aud/nonce/disclosure mismatch (replay defence).
    """
    if "~" in compact:  # SD-JWT-VC wire form: <JWS>~<disclosure>~...
        r = verify_sd_jwt(
            compact, public_key=public_key, resolver=resolver, expected_vc_type=_VC_TYPE,
            require_key_binding=require_key_binding,
            expected_aud=expected_aud, expected_nonce=expected_nonce,
        )
        claims = {**r.visible_claims, **r.disclosed_claims} if r.valid else {}
        return AttestationVerifyResult(
            valid=r.valid, mode="sd-jwt", claims=claims,
            decision_id=claims.get("decision_id"),
            reproducible=bool(claims.get("reproducible", False)),
            key_bound=r.key_bound, holder_did=r.holder_did,
            error=r.error,
        )
    r = verify(compact, public_key=public_key, resolver=resolver)
    claims = r.payload if (r.valid and isinstance(r.payload, dict)) else {}
    return AttestationVerifyResult(
        valid=r.valid, mode="jws", claims=claims,
        decision_id=claims.get("decision_id"),
        reproducible=bool(claims.get("reproducible", False)),
        error=r.error,
    )


__all__ = [
    "Attestation",
    "SignedAttestation",
    "AttestationVerifyResult",
    "attest",
    "present_attestation",
    "verify_attestation",
]
