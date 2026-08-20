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


def sign_pack_manifest(keypair: Any, *, pack: str, digest: str,
                       rows: int, outcomes: dict[str, int]) -> dict:
    """One signature over a whole adjudicated pack.

    Signing 360 edges separately proves no edge was altered and says nothing
    about an edge being dropped. Hashing the manifest catches both, because the
    row count and the pack digest are inside the thing being signed.
    """
    from arche.sign import sign as sign_jws

    body = {
        "schema": "arche.studio.pack-manifest.v1",
        "pack": pack,
        "pack_digest": digest,
        "rows": rows,
        "outcomes": dict(sorted(outcomes.items())),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return {"manifest": body,
            "jws": sign_jws(body, keypair.private_key, kid=keypair.did_key)}
