#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""The reviewer's signing key: one, kept, reused.

    data/review_packs/_studio_key.pem   (gitignored, 0600 where the OS allows)

The problem this solves
-----------------------
`sign_edges` needs a private key, and the studio was generating a fresh one on
every call. That produces a signature which verifies as `valid` and
`self-asserted`: it proves nothing was altered, and proves nothing at all about
who signed, because the key existed for one HTTP request and then vanished.

A signature nobody can attribute is a checksum with extra steps.

So the key is created once and loaded thereafter. The `did:key` is the public
half and it *is* the identifier. There is no certificate authority and nothing
to register: you publish the did:key wherever people already trust you to say
things (a README, an email footer, a DNS record), and a recipient who has it
can move from `valid` to `trusted`.

The three answers a recipient can get
-------------------------------------
arche already models the distinction, and it is the part worth understanding:

* ``verify(jws, allow_did_key_from_kid=True)`` -> **valid, not trusted.**
  Nothing changed since signing. The signer told you which key to use, so this
  says nothing about who they are.
* ``verify(jws, public_key=<pinned>)`` -> **trusted.** You got their key by some
  other route and pinned it. This is the normal case between two parties who
  have met.
* ``verify(jws, resolver=<fn>)`` -> **trusted.** You look the key up somewhere
  you control.

Only the second and third are attribution. The studio labels the first honestly
rather than letting a green tick imply more than it earned.

Signing a whole result, not 360 edges
-------------------------------------
Signing every edge separately answers "was this row altered" and answers
"was a row *removed*" not at all. For a pack, sign the manifest: the pack digest
plus its counts. One signature, and a missing row changes the digest.

`sign_pack_manifest` below does that. Per-edge signatures still make sense when
one decision travels on its own to someone who should not see the rest.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


def load_or_create(path: Path) -> Any:
    """The studio's keypair. Created on first use, loaded every time after."""
    from arche.sign import generate_keypair, load_private_key_pem, save_private_key

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return load_private_key_pem(path.read_bytes())

    kp = generate_keypair()
    save_private_key(kp, path)
    # Best effort: on POSIX this matters, on Windows it is a no-op and the file
    # is protected by the user profile instead.
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return kp


def public_identity(keypair: Any) -> dict:
    """What to publish so a recipient can move from `valid` to `trusted`."""
    from arche.sign import export_public_pem

    return {
        "did_key": keypair.did_key,
        "public_pem": export_public_pem(keypair).decode()
        if isinstance(export_public_pem(keypair), bytes)
        else export_public_pem(keypair),
        "note": ("Publish the did_key. A recipient who pins it gets trusted=True; "
                 "one who does not gets valid=True and trusted=False, which "
                 "proves integrity and not authorship."),
    }


def _ledger_digest(ledger: list) -> str:
    """One place that decides what a ledger hashes to.

    Signing and verifying computing this separately is how the two quietly stop
    agreeing.
    """
    canonical = json.dumps(ledger, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_adjudication(keypair: Any, *, pack: str, content_digest: str,
                      rows: int, marks: dict) -> dict:
    """Sign what each decision was adjudicated as, not how many of each there were.

    The previous version signed the pack digest, the row count, and a tally of
    outcomes. That binds nothing to anything: two adjudications that disagree on
    every single decision produce identical counts, so they produce an identical
    signed payload and an identical signature. It proved a pack of 360 rows had
    180 `same_entity` marks and said nothing about WHICH 180.

    So the ledger is the thing hashed: one row per decision id, carrying the
    outcome, the reviewer who chose it, and the reason. Sorted by decision id,
    so the digest describes the adjudication rather than the order somebody
    happened to work in. `outcomes_sha256` goes inside the signed body, which is
    what binds decision to outcome.

    The ledger itself is returned alongside, unsigned and in full. A verifier
    recomputes the digest from it and checks that against the signature; anyone
    editing one mark has to forge a signature rather than swap a file.

    What this still does not establish is WHO reviewed. `reviewer` is a string
    somebody typed and `marked_at` comes from the local clock. The signature
    proves the ledger has not changed since it was signed, by the holder of one
    key. It does not prove the names in it are real people or the times are
    true. Read `valid` and `trusted` the same way the rest of arche does.
    """
    from arche.sign import sign as sign_jws

    ledger = sorted(
        (
            {
                "decision_id": did,
                "outcome": mark.get("outcome", ""),
                "reviewer": mark.get("reviewer", ""),
                "reason": mark.get("reason", "") or "",
                "marked_at": mark.get("marked_at", ""),
            }
            for did, mark in marks.items()
        ),
        key=lambda r: r["decision_id"],
    )

    counts: dict[str, int] = {}
    for entry in ledger:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1

    body = {
        "schema": "arche.studio.adjudication.v2",
        "pack": pack,
        # The CONTENT digest, not the id-membership one. A pack whose names were
        # edited after signing must not still verify.
        "pack_content_sha256": content_digest,
        "rows": rows,
        "marked": len(ledger),
        # This is the binding. Recompute it from `ledger` to check.
        "outcomes_sha256": _ledger_digest(ledger),
        # Kept for reading at a glance. It is a summary of the line above, never
        # a substitute for it.
        "outcomes": dict(sorted(counts.items())),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return {"manifest": body, "ledger": ledger,
            "jws": sign_jws(body, keypair.private_key, kid=keypair.did_key)}


def verify_adjudication(signed: dict, *, public_key: Any = None) -> dict:
    """Check the signature, then check the ledger the signature covers.

    The version this replaces did the second half only. It recomputed the ledger
    digest and compared it against a field in the same unsigned document, and
    never looked at the `jws` at all. Replace both the ledger and the manifest
    field it claims and the old function said `outcomes_match=True`. A function
    named verify that ignores the signature is worse than no function.

    Three questions, answered in order, because a later one is meaningless if an
    earlier one fails:

    1. Does the signature verify at all, and against whose key?
    2. Is the manifest inside the signature the manifest in front of us? A valid
       signature over a DIFFERENT manifest proves nothing about this one.
    3. Does the ledger still hash to what that manifest claims? This is what
       binds each decision id to its outcome.

    `valid` and `trusted` mean what they mean everywhere else in arche: `valid`
    says the signature matches the key it names, `trusted` says that key is one
    the caller pinned. Without `public_key` you get integrity, not attribution.
    """
    from arche.sign import verify as verify_jws

    manifest = signed.get("manifest") or {}
    ledger = signed.get("ledger") or []
    jws = signed.get("jws")

    report: dict[str, Any] = {
        "ok": False, "signature_valid": False, "trusted": False,
        "manifest_matches_signature": False, "outcomes_match": False,
        "marked": len(ledger), "problems": [],
    }

    if not jws:
        report["problems"].append("no `jws`; this adjudication is unsigned")
        return report

    try:
        result = verify_jws(jws, public_key=public_key,
                            allow_did_key_from_kid=public_key is None)
    except Exception as exc:  # noqa: BLE001 - a bad signature is an answer
        report["problems"].append(f"signature does not verify: {exc}")
        return report

    report["signature_valid"] = bool(getattr(result, "valid", False))
    report["trusted"] = bool(getattr(result, "trusted", False))
    if not report["signature_valid"]:
        report["problems"].append("signature does not verify")
        return report

    signed_payload = getattr(result, "payload", None) or {}
    # The signed manifest is the authority. Comparing the digest lets a caller
    # see that the document they hold is the document that was signed.
    signed_digest = signed_payload.get("manifest_sha256")
    report["manifest_matches_signature"] = (
        bool(signed_digest) and signed_digest == manifest.get("manifest_sha256"))
    if not report["manifest_matches_signature"]:
        report["problems"].append(
            "the manifest in this document is not the one that was signed")
        return report

    recomputed = _ledger_digest(ledger)
    claimed = signed_payload.get("outcomes_sha256", "")
    report["recomputed_outcomes_sha256"] = recomputed
    report["claimed_outcomes_sha256"] = claimed
    report["outcomes_match"] = recomputed == claimed
    if not report["outcomes_match"]:
        report["problems"].append(
            "the ledger does not hash to the digest the signature covers; it "
            "has been edited or swapped")
        return report

    report["ok"] = True
    return report
