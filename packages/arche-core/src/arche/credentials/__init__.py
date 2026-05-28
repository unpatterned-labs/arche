# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche.credentials — Verifiable Credentials for arche identity workflows.

Per the verifiability roadmap locked decision (2026-06-02): arche emits
**SD-JWT-VC** (IETF selective-disclosure JWT format, used by EUDI Wallet
ARF and MOSIP Inji) as the v0.2 credential format. JSON-LD VC 1.1 via
``didkit`` is deferred to Stage 3 as the ``arche-core[didkit]`` extra.

Public API::

    from arche.credentials import (
        issue_sd_jwt,
        verify_sd_jwt,
        present,
        envelope_to_sd_jwt,
        SDJWTResult,
        SDJWTVerifyResult,
    )

    # Issuer: emit an SD-JWT-VC where every detection category is
    # selectively disclosable.
    result = issue_sd_jwt(
        claims={
            "name": "Adesola Okonkwo",
            "nin_present": True,
            "bvn_present": True,
            "jurisdiction": "NG",
        },
        issuer_key=keypair,
        disclosable_claims=["nin_present", "bvn_present"],
    )

    # Holder: present only the BVN-presence claim, hide the NIN.
    presentation = present(result.compact, disclose=["bvn_present"])

    # Verifier: recover only what was disclosed.
    v = verify_sd_jwt(presentation)
    assert v.valid
    assert v.claims["bvn_present"] is True
    assert "nin_present" not in v.claims

The ``envelope_to_sd_jwt`` helper converts an existing
:class:`arche.sign.ArcheSignedDocument` into an SD-JWT-VC — the same
content, re-framed for wallet ecosystems.
"""

from arche.credentials.sd_jwt import (
    SD_JWT_TYP,
    SDJWTResult,
    SDJWTVerifyResult,
    envelope_to_sd_jwt,
    issue_sd_jwt,
    present,
    verify_sd_jwt,
)

__all__ = [
    "issue_sd_jwt",
    "verify_sd_jwt",
    "present",
    "envelope_to_sd_jwt",
    "SDJWTResult",
    "SDJWTVerifyResult",
    "SD_JWT_TYP",
]
