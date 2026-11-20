# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Verifiable credentials over reconcile decisions -- a spike.

A credential here states a *link*, not a fact about a record: "site A is the
same site as B", "site A is operated by organisation B", or, from a reviewer,
"A and B are not the same". It wraps a reconcile edge in a W3C Verifiable
Credential 2.0 envelope, secured as a JWS (VC-JOSE-COSE, ``typ: vc+jwt``) with
the Ed25519 signing arche already has.

Three properties make it worth more than a signed JSON blob:

* **Self-verifying.** The edge (ids and numeric evidence only) and the run's
  pins travel inside the credential, so a verifier recomputes the decision id
  rather than trusting the one written down.
* **Levelled.** ``machine`` (arche decided, nobody looked), ``adjudicated`` (a
  reviewer's signed label is embedded and checked), ``attested`` (an issuer
  with a resolvable identity stands behind it). A signature proves who said
  something, not that it is right; the level says what kind of saying it was,
  and the verifier refuses a level the contents do not support.
* **Criterion-bound.** The credential carries a digest of the identity
  criterion the link was judged under, so ``same_as`` under "same production
  site" cannot be read as ``same_as`` under "same legal entity".

What it does not do yet: status lists (revocation), ``did:web`` resolution, or
JSON-LD processing. The ``@context`` below is provisional and not yet
published; nothing here dereferences it.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from arche.ids import content_hash, edge_decision_id
from arche.sign import Keypair, sign, verify

VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
#: Provisional: not yet published, never dereferenced by this module.
ARCHE_CONTEXT = "https://unpatterned.org/ns/arche/credentials/v1"
LABEL_SCHEMA = "arche.adjudication_label.v1"
LEVELS = ("machine", "adjudicated", "attested")
_TYPE_BY_CLAIM = {
    "same_as": "SiteIdentityCredential",
    "operated_by": "OperatorCredential",
    "not_same_as": "NonIdentityCredential",
}
_LABEL_TO_CLAIM = {"same_as": "same_as", "operated_by": "operated_by",
                   "none_of_these": "not_same_as"}


class CredentialError(ValueError):
    """Refused to build a credential the evidence does not support."""


def criterion_digest(text: str) -> str:
    """Address of an identity criterion's exact wording."""
    return content_hash({"criterion": text.strip()}, prefix="crit")


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── reviewer labels ─────────────────────────────────────────────────────────

def sign_label(keypair: Keypair, *, decision_id: str, label: str, criterion: str,
               at: str | None = None) -> str:
    """A reviewer's signed verdict on one decision, under one criterion.

    ``criterion`` is the digest from :func:`criterion_digest`. The reviewer's
    key is a ``did:key``; that it belongs to a real, named person is something
    only the verifier's own key list can establish.
    """
    if label not in _LABEL_TO_CLAIM and label != "cannot_tell":
        raise CredentialError(f"unknown label {label!r}")
    payload = {"schema": LABEL_SCHEMA, "decision_id": decision_id, "label": label,
               "criterion": criterion, "reviewer": keypair.did_key, "at": at or _now()}
    return sign(payload, keypair.private_key, kid=keypair.did_key, typ="arche-label+jws")


def _label_payload(label_jws: str) -> dict:
    # Read without authenticating: building only needs the claim's shape.
    # Authentication is the verifier's job, against keys it chose.
    check = verify(label_jws, allow_did_key_from_kid=True)
    if not check.valid or not isinstance(check.payload, dict):
        raise CredentialError(f"label does not verify: {check.error}")
    return check.payload


# ── build and issue ─────────────────────────────────────────────────────────

def _check_edge_is_shareable(edge: Mapping[str, Any]) -> None:
    allowed = {"a_id", "b_id", "score", "decision", "evidence", "distinctive_max",
               "candidate", "decision_id", "vetoes", "refuted_by"}
    extra = set(edge) - allowed
    if extra:
        raise CredentialError(f"edge carries fields a credential must not: {sorted(extra)}")
    for k, v in (edge.get("evidence") or {}).items():
        if v is not None and not isinstance(v, (int, float)):
            raise CredentialError(f"evidence {k!r} is not numeric")


def build_credential(
    edge: Mapping[str, Any],
    pins: Mapping[str, Any],
    *,
    subject: Mapping[str, str],
    obj: Mapping[str, str],
    level: str,
    issuer: str,
    criterion: str,
    label_jws: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    reference_freshness: Mapping[str, str] | None = None,
    previous: str | None = None,
) -> dict[str, Any]:
    """Wrap one reconcile edge as an unsigned VC 2.0 credential.

    ``subject`` and ``obj`` name the two records in public schemes, e.g.
    ``{"scheme": "gb-companies-house", "id": "01234567"}``; their ``id`` must
    be the edge's ``a_id`` / ``b_id``, so the credential cannot describe a
    different pair from the one that was decided.
    """
    if level not in LEVELS:
        raise CredentialError(f"level must be one of {LEVELS}")
    _check_edge_is_shareable(edge)
    if subject.get("id") != edge.get("a_id") or obj.get("id") != edge.get("b_id"):
        raise CredentialError("subject/object ids must be the edge's a_id/b_id")
    did = edge_decision_id(dict(edge), dict(pins))
    if edge.get("decision_id") and edge["decision_id"] != did:
        raise CredentialError("edge decision_id does not recompute from edge and pins")
    relation = str(pins.get("relation") or "same_as")

    if level == "machine":
        if edge.get("decision") != "match":
            raise CredentialError(
                f"a machine credential asserts a link; this edge is {edge.get('decision')!r}")
        claim = relation
    else:
        if label_jws is None:
            raise CredentialError(f"a {level} credential needs a reviewer's signed label")
        lab = _label_payload(label_jws)
        if lab.get("decision_id") != did:
            raise CredentialError("label is for a different decision")
        if lab.get("criterion") != criterion:
            raise CredentialError("label was judged under a different criterion")
        if lab.get("label") not in _LABEL_TO_CLAIM:
            raise CredentialError(f"label {lab.get('label')!r} asserts nothing")
        claim = _LABEL_TO_CLAIM[lab["label"]]
        if claim != "not_same_as" and claim != relation:
            raise CredentialError(
                f"reviewer said {claim!r} but the run decided {relation!r} links")
    if level == "attested":
        if issuer.startswith("did:key:"):
            raise CredentialError("attested needs an issuer with a resolvable identity, "
                                  "not a self-certifying did:key")
        if not reference_freshness:
            raise CredentialError("attested needs the reference snapshot dates it relied on")

    decision: dict[str, Any] = {
        "decisionId": did, "level": level, "criterion": criterion,
        "edge": {k: v for k, v in edge.items() if k != "decision_id"},
        "pins": dict(pins),
    }
    if label_jws:
        decision["label"] = label_jws
    cred: dict[str, Any] = {
        "@context": [VC_CONTEXT, ARCHE_CONTEXT],
        "id": f"urn:uuid:{uuid.uuid4()}",
        "type": ["VerifiableCredential", _TYPE_BY_CLAIM[claim]],
        "issuer": issuer,
        "validFrom": valid_from or _now(),
        "credentialSubject": {"claim": claim, "subject": dict(subject),
                              "object": dict(obj), "decision": decision},
    }
    if valid_until:
        cred["validUntil"] = valid_until
    if reference_freshness:
        cred["credentialSubject"]["referenceFreshness"] = dict(reference_freshness)
    if previous:
        cred["previous"] = previous
    return cred


def issue(credential: Mapping[str, Any], keypair: Keypair, *, kid: str | None = None) -> str:
    """Secure a credential as a JWS (``typ: vc+jwt``) with the issuer's key."""
    issuer = credential["issuer"]
    if issuer.startswith("did:key:") and issuer != keypair.did_key:
        raise CredentialError("issuer is a did:key that is not this keypair")
    return sign(dict(credential), keypair.private_key,
                kid=kid or (issuer if issuer.startswith("did:key:") else keypair.did_key),
                typ="vc+jwt")


# ── verify ──────────────────────────────────────────────────────────────────

@dataclass
class CredentialCheck:
    signature_valid: bool = False
    issuer_trusted: bool = False
    decision_id_ok: bool = False
    level_ok: bool = False
    label_valid: bool | None = None
    label_trusted: bool | None = None
    current: bool = True
    problems: list[str] = field(default_factory=list)
    credential: dict | None = None

    @property
    def ok(self) -> bool:
        """Integrity: signed, self-consistent, at the level it claims, in date.
        Says nothing about whom to believe -- read ``issuer_trusted`` and
        ``label_trusted`` for that."""
        return (self.signature_valid and self.decision_id_ok and self.level_ok
                and self.current and self.label_valid is not False)


def verify_credential(
    token: str,
    *,
    issuer_key: Any = None,
    resolver: Callable[[str], Any] | None = None,
    reviewer_keys: Mapping[str, Any] | None = None,
    now: str | None = None,
) -> CredentialCheck:
    """Check a credential end to end. Trust comes only from keys you supply."""
    out = CredentialCheck()
    trusted_path = issuer_key is not None or resolver is not None
    sig = verify(token, public_key=issuer_key, resolver=resolver,
                 allow_did_key_from_kid=not trusted_path)
    out.signature_valid = bool(sig.valid)
    out.issuer_trusted = bool(sig.valid and sig.trusted)
    if not sig.valid or not isinstance(sig.payload, dict):
        out.problems.append(f"signature: {sig.error}")
        return out
    if sig.header.get("typ") != "vc+jwt":
        out.problems.append("not a vc+jwt")
    cred = out.credential = sig.payload
    if cred.get("issuer", "").startswith("did:key:") and sig.kid != cred["issuer"]:
        out.problems.append("signing key is not the stated issuer")
        out.signature_valid = False

    cs = cred.get("credentialSubject", {})
    dec = cs.get("decision", {})
    edge, pins = dec.get("edge", {}), dec.get("pins", {})
    out.decision_id_ok = edge_decision_id(edge, pins) == dec.get("decisionId")
    if not out.decision_id_ok:
        out.problems.append("decision id does not recompute from the embedded edge and pins")

    level, claim = dec.get("level"), cs.get("claim")
    relation = str(pins.get("relation") or "same_as")
    if (edge.get("a_id"), edge.get("b_id")) != (cs.get("subject", {}).get("id"),
                                                cs.get("object", {}).get("id")):
        out.problems.append("subject/object are not the decided pair")
    elif level == "machine":
        out.level_ok = edge.get("decision") == "match" and claim == relation
    elif level in ("adjudicated", "attested") and dec.get("label"):
        lab = verify(dec["label"], public_key=(reviewer_keys or {}).get(
            _kid(dec["label"])), allow_did_key_from_kid=True)
        out.label_valid = bool(lab.valid)
        out.label_trusted = bool(lab.valid and lab.trusted)
        p = lab.payload if isinstance(lab.payload, dict) else {}
        expected = _LABEL_TO_CLAIM.get(p.get("label"))
        out.level_ok = (lab.valid and p.get("decision_id") == dec.get("decisionId")
                        and p.get("criterion") == dec.get("criterion")
                        and expected == claim
                        and (claim == "not_same_as" or claim == relation))
        if level == "attested" and cred.get("issuer", "").startswith("did:key:"):
            out.level_ok = False
    if not out.level_ok:
        out.problems.append(f"contents do not support level {level!r}")
    if _TYPE_BY_CLAIM.get(claim) not in cred.get("type", []):
        out.level_ok = False
        out.problems.append("type does not match the claim")

    when = now or _now()
    if cred.get("validUntil") and when > cred["validUntil"]:
        out.current = False
        out.problems.append("expired")
    if cred.get("validFrom") and when < cred["validFrom"]:
        out.current = False
        out.problems.append("not yet valid")
    return out


def _kid(jws: str) -> str | None:
    import base64
    import json
    head = jws.split(".")[0]
    try:
        return json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))).get("kid")
    except ValueError:
        return None


__all__ = ["CredentialCheck", "CredentialError", "LEVELS", "build_credential",
           "criterion_digest", "issue", "sign_label",
           "verify_credential"]
