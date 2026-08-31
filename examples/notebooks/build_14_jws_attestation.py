# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Generate the JWS crosswalk-decision notebook.

Run from the repository root:

    uv run python examples/notebooks/build_14_jws_attestation.py
"""
from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    """Append one Markdown notebook cell."""
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    """Append one executable notebook cell."""
    cells.append((CODE, text.strip("\n")))


md("""
# Attesting a crosswalk decision with JWS

This notebook separates two questions that are easy to conflate:

1. **Should these records be linked?** Arche's deterministic crosswalk answers
   this from the records, comparator pack, thresholds, and evidence.
2. **Who attests to that decision, and did it change?** A JWS answers this after
   the decision is made.

The signing key does **not** alter a score, `match` or `review` decision,
evidence, or `decision_id`. It signs the result that already exists.
""")

md("""
## Create one decision

The records below represent the same facility with a spelling difference. The
crosswalk gets no identifier, signing key, or issuer information. It only gets
names and coordinates.
""")

code("""
from arche.resolve import reconcile

registry = [{
    "id": "registry:001",
    "name": "Harbour View Health Centre",
    "lat": 6.5930,
    "lon": 3.3577,
}]
map_data = [{
    "id": "map:abc",
    "name": "Harbor View Health Centre",
    "lat": 6.5931,
    "lon": 3.3578,
}]

result = reconcile(registry, map_data, entity="place")
edge = result["matches"][0]

print("decision:", edge["decision"])
print("score:", edge["score"])
print("decision_id:", edge["decision_id"])
print("evidence:", edge["evidence"])
print("pins:", result["pins"])
""")

md("""
`decision_id` starts with `xwd:sha256:`. It is a content hash, not a JWS. The
pins say which engine, comparator configuration, blocker, thresholds, and
frequency tables produced the decision.
""")

md("""
## Sign the same result with two keys

These generated keys are for a demonstration only. In a real service, keep the
private key in a controlled signer or key-management system and distribute the
public key through a trusted channel.
""")

code("""
from arche.resolve.reconcile import sign_edges
from arche.sign import generate_keypair

alice = generate_keypair()
bob = generate_keypair()

alice_attestation = sign_edges(
    result,
    private_key=alice.private_key,
    kid=alice.did_key,
)[0]
bob_attestation = sign_edges(
    result,
    private_key=bob.private_key,
    kid=bob.did_key,
)[0]

alice_jws = alice_attestation["jws"]
bob_jws = bob_attestation["jws"]

print("same decision ID:", alice_attestation["decision_id"] == bob_attestation["decision_id"])
print("different JWS values:", alice_jws != bob_jws)
print("compact JWS segments:", alice_jws.count(".") + 1)
""")

md("""
The decision ID remains the same because the decision did not change. The JWS
values differ because Alice and Bob used different private keys. A compact JWS
has three Base64URL segments: `header.payload.signature`.
""")

md("""
## Verify before reading the payload

You can Base64URL-decode the header and payload for debugging, but do not trust
them until verification succeeds against a public key you already trust.
""")

code("""
from arche.sign import verify

alice_check = verify(alice_jws, public_key=alice.public_key)
bob_check = verify(alice_jws, public_key=bob.public_key)

print("Alice key validates Alice JWS:", alice_check.valid, alice_check.trusted)
print("Bob key validates Alice JWS:", bob_check.valid, bob_check.trusted)

payload = alice_check.payload
print("signed schema:", payload["schema"])
print("signed decision ID:", payload["decision_id"])
print("payload decision ID matches result:", payload["decision_id"] == edge["decision_id"])
print("signed pins match result:", payload["pins"] == result["pins"])
""")

md("""
`valid` means the signature matches the supplied key. `trusted` means the key
came from the trusted `public_key` supplied to verification. Do not let a token
choose its own trust root in a production workflow.
""")

md("""
## Detect tampering

Changing even one character in the signature makes the compact JWS fail
verification. The underlying decision is unaffected, but the attestation is no
longer usable.
""")

code("""
header, payload_part, signature = alice_jws.split(".")
replacement = "A" if signature[-1] != "A" else "B"
tampered_jws = f"{header}.{payload_part}.{signature[:-1]}{replacement}"
tampered_check = verify(tampered_jws, public_key=alice.public_key)

print("tampered JWS validates:", tampered_check.valid)
print("verification error:", tampered_check.error)
""")

md("""
## What would change a merge decision?

A key never changes the decision. Re-running `crosswalk` with changed source
records, comparators, thresholds, blocking policy, or frequency tables can
change the score, evidence, decision, pins, and `decision_id`. That new result
must be signed again.
""")

code("""
repeat = reconcile(registry, map_data, entity="place")
same_decision_id = repeat["matches"][0]["decision_id"] == edge["decision_id"]
print("same inputs give the same decision ID:", same_decision_id)

# A signer may attest to the repeat, but cannot make it a different merge.
repeat_attestation = sign_edges(
    repeat,
    private_key=alice.private_key,
    kid=alice.did_key,
)[0]
signing_preserves_id = repeat_attestation["decision_id"] == edge["decision_id"]
print("signing preserves the decision ID:", signing_preserves_id)
""")

md("""
## Keep and share

Store the crosswalk output, source hashes, decision pins, the compact JWS, and
the signer identity together. Share the public key through a trusted channel.
Never share a private key or use a notebook-generated key for production.
""")

notebook = {
    "cells": [
        {
            "cell_type": kind,
            "id": f"jws-{index:02d}",
            "metadata": {},
            **(
                {"source": text.splitlines(keepends=True)}
                if kind == MD
                else {
                    "source": text.splitlines(keepends=True),
                    "outputs": [],
                    "execution_count": None,
                }
            ),
        }
        for index, (kind, text) in enumerate(cells, start=1)
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

output = Path(__file__).resolve().parent / "14_jws_attestation.ipynb"
output.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {output} ({len(cells)} cells)")
