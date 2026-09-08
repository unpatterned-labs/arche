# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Attested answers: a signed envelope over one thing arche said.

When an agent asks arche a question over MCP or HTTP and then acts on the
answer, the record of that action is usually the agent's own transcript --
"arche said these two were the same". Nothing in the transcript stops the
agent, or whoever edits the transcript afterwards, from saying arche said
something else. An attestation is the answer's own receipt: a JWS, signed by
the arche installation's key, over the tool that was called, a hash of the
inputs, a hash of the response, who asked, and every decision id the
response carried.

    from arche.attest import attest, verify_attestation
    from arche.sign import generate_keypair

    key = generate_keypair()
    env = attest("compare", inputs, response, keypair=key)
    check = verify_attestation(env, inputs=inputs, response=response,
                               public_key=key.public_key)
    check.ok          # signature valid, both hashes match, key was pinned

What it proves, and what it does not. The signature proves the envelope was
made by the holder of one key and not altered since; with the inputs and
response beside it, the two hashes prove *this* question got *this* answer.
``trusted`` is true only when the verifier supplied the key or a resolver --
a key decoded from the token's own ``kid`` is self-asserted and never
trusted, the same rule ``arche.sign.verify`` applies everywhere. ``caller``
is whatever the transport knew: an identity header behind an auth proxy, or
nothing on a stdio MCP session. It is a claim the signer makes, not one the
signature establishes.

The envelope carries hashes and ids, never a value, so it is as shareable as
a decision id. The inputs and the response stay with whoever holds them.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arche.ids import canonical_json

ATTESTATION_SCHEMA = "arche.attestation.v1"

#: The ids arche mints: ``prefix:alg:hex``.
_ID = re.compile(r"^(dec|xwd|red|rec|ent):(sha256|hmac-sha256):[0-9a-f]{64}$")


def _digest(payload: Any) -> str:
    """sha256 over the canonical JSON: sorted keys, floats at four places, so
    a response re-serialised by a different client still hashes the same."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def decision_ids_in(response: Any) -> list[str]:
    """Every decision id a response carries, wherever it sits.

    Walks dicts and lists for values under a ``decision_id`` key -- or inside a
    ``decision_ids`` list -- that look like an arche id. Sorted and unique, so
    the envelope's list does not depend on the response's layout.
    """
    found: set[str] = set()

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key in ("decision_id", "decision_ids") and _ID.match(node):
            found.add(node)

    walk(response)
    return sorted(found)


def attest(tool: str, inputs: Any, response: Any, *, keypair: Any,
           caller: str | None = None, decision_ids: list[str] | None = None,
           issued_at: datetime | None = None) -> dict[str, Any]:
    """The signed envelope over one answer.

    ``keypair`` is an :class:`arche.sign.Keypair`; its ``did_key`` is the
    signer and goes in the JWS ``kid`` so a verifier who has pinned it can
    move from *valid* to *trusted*. ``decision_ids`` defaults to whatever the
    response carries. The envelope's plain fields repeat what the JWS signs,
    for a reader without a verifier; only the JWS is evidence.
    """
    from arche import __version__
    from arche.sign import sign

    body = {
        "schema": ATTESTATION_SCHEMA,
        "tool": tool,
        "inputs_sha256": _digest(inputs),
        "response_sha256": _digest(response),
        "caller": caller,
        "decision_ids": sorted(set(decision_ids)) if decision_ids is not None
        else decision_ids_in(response),
        "issued_at": (issued_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "engine": f"arche-core@{__version__}",
        "signer": keypair.did_key,
    }
    return {**body, "jws": sign(body, keypair.private_key, kid=keypair.did_key, typ="arche+jws")}


@dataclass
class AttestationCheck:
    """What a verifier can say about an envelope.

    ``valid`` -- the signature holds over the signed body. ``trusted`` -- and
    the key came from the verifier, not the token. ``inputs_match`` and
    ``response_match`` are ``None`` when that side was not supplied, else
    whether its hash agrees with the signed one. ``ok`` is ``valid`` and every
    supplied side matching; it does not require ``trusted``, because
    integrity and attribution are different questions and the caller decides
    which one they are asking. ``problems`` says which check failed, in words.
    """

    valid: bool
    trusted: bool
    signer: str | None
    tool: str | None
    decision_ids: list[str] = field(default_factory=list)
    inputs_match: bool | None = None
    response_match: bool | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.valid and self.inputs_match is not False and self.response_match is not False

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "valid": self.valid, "trusted": self.trusted,
                "signer": self.signer, "tool": self.tool, "decision_ids": self.decision_ids,
                "inputs_match": self.inputs_match, "response_match": self.response_match,
                "problems": list(self.problems)}


def verify_attestation(envelope: dict[str, Any], *, inputs: Any = None, response: Any = None,
                       public_key: Any = None, resolver: Any = None) -> AttestationCheck:
    """Check an envelope, and the inputs and response beside it when given.

    Verifies the JWS with the verifier's key (``public_key``, an Ed25519 key
    or a did:key string) or ``resolver``; with neither, the key is decoded
    from the token's own ``kid`` and the result is *valid, not trusted*. The
    plain fields of the envelope are ignored: the signed body is the claim,
    and a mismatch between the two is reported as a problem.
    """
    from arche.sign import decode_did_key, verify

    jws = envelope.get("jws") if isinstance(envelope, dict) else None
    if not jws:
        return AttestationCheck(valid=False, trusted=False, signer=None, tool=None,
                                problems=["no jws in the envelope"])
    if isinstance(public_key, str):
        public_key = decode_did_key(public_key)
    result = verify(jws, public_key=public_key, resolver=resolver,
                    allow_did_key_from_kid=public_key is None and resolver is None)
    if not result.valid:
        return AttestationCheck(valid=False, trusted=False, signer=result.kid, tool=None,
                                problems=[f"signature: {result.error}"])
    body = result.payload if isinstance(result.payload, dict) else {}
    problems: list[str] = []
    if body.get("schema") != ATTESTATION_SCHEMA:
        problems.append(f"schema {body.get('schema')!r} is not {ATTESTATION_SCHEMA}")
    for k in ("tool", "inputs_sha256", "response_sha256", "decision_ids", "caller"):
        if k in envelope and envelope[k] != body.get(k):
            problems.append(f"envelope field {k!r} differs from what was signed")
    inputs_match = response_match = None
    if inputs is not None:
        inputs_match = _digest(inputs) == body.get("inputs_sha256")
        if not inputs_match:
            problems.append("the inputs supplied do not hash to what was signed")
    if response is not None:
        response_match = _digest(response) == body.get("response_sha256")
        if not response_match:
            problems.append("the response supplied does not hash to what was signed")
    return AttestationCheck(valid=not any(p.startswith("schema") or p.startswith("envelope")
                                          for p in problems),
                            trusted=result.trusted, signer=body.get("signer") or result.kid,
                            tool=body.get("tool"), decision_ids=list(body.get("decision_ids") or []),
                            inputs_match=inputs_match, response_match=response_match,
                            problems=problems)


def signing_key(path: str | Path | None = None) -> Any:
    """The installation's signing key, or ``None`` when there is none.

    ``path`` or ``ARCHE_SIGNING_KEY`` names a PEM written by ``arche attest
    keygen``. Never generated on the fly: a key that exists for one process
    and vanishes signs envelopes nobody can attribute, which is a checksum
    with extra steps. Absent key, no attestation, and the surfaces say so.
    """
    from arche.sign import load_private_key_pem

    chosen = path or os.environ.get("ARCHE_SIGNING_KEY")
    if not chosen:
        return None
    file = Path(chosen).expanduser()
    if not file.exists():
        raise FileNotFoundError(
            f"signing key {file} does not exist; make one with: arche attest keygen {file}")
    return load_private_key_pem(file.read_bytes())


__all__ = ["ATTESTATION_SCHEMA", "AttestationCheck", "attest", "decision_ids_in",
           "signing_key", "verify_attestation"]
