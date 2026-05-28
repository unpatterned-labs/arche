# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Digital identity detection — DIDs and crypto wallet addresses.

Public API per the 2026-05-22 detection-first reposition::

    from arche.detect.digital_id import (
        detect_digital_ids,    # all flavours combined
        detect_did,            # W3C DIDs (did:key, did:web, did:ion)
        detect_crypto_wallet,  # BTC + ETH addresses
    )

    detections = detect_digital_ids(
        "Wallet 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0 "
        "controlled by did:key:z6MkpTHR8VNsBxYAAWHut2Geadd9jSrnQ..."
    )

Cross-cutting (not country-specific). Public module name per the
eng review §1 issue 1 decision — matches ``arche.detect.ip``.

Returns :class:`arche.workflow._primitive.Detection` directly.

Detection rules:

-   **DIDs (W3C decentralized identifiers)**:
    Pattern: ``did:METHOD:IDENTIFIER`` where METHOD is lowercase
    alphanumeric and IDENTIFIER is base58/base64-url/alphanumeric with
    dots / colons / hyphens. Known methods (``key``, ``web``, ``ion``,
    ``ethr``, ``polygon``, ``jwk``) match at confidence 1.0; unknown
    methods match at 0.7 (the shape is distinctive enough to be a real
    DID, but we can't validate the method-specific format).
    Category: ``PII-2-DID``.

-   **Bitcoin addresses**:
    - **base58check (P2PKH / P2SH)**: starts with ``1`` (mainnet
      P2PKH), ``3`` (mainnet P2SH), or ``m`` / ``n`` (testnet), 26-35
      chars from the base58 alphabet. Shape match at confidence 0.85.
    - **bech32 (SegWit)**: starts with ``bc1`` (mainnet) or ``tb1``
      (testnet), 39-90 chars from the bech32 alphabet. Confidence 0.9.
    Category: ``PII-5-CRYPTO_WALLET``.

-   **Ethereum addresses**:
    Pattern: ``0x`` + 40 hex characters. EIP-55 checksum verification
    is **not** performed in v0.2.0a2 (would require importing
    ``eth_utils`` / keccak; deferred to v0.3). Confidence 0.85 for
    pure-lowercase or pure-uppercase, 0.9 for mixed-case (likely EIP-55
    intent). Category: ``PII-5-CRYPTO_WALLET``.

False positives are inevitable for crypto wallets given their generic
shape (hex strings, base58 strings). Production callers should compose
with context (transaction context, "wallet" / "address" keywords) or
push to an LLM-anchored disambiguation step. v0.2.0a2 documents this
tradeoff explicitly rather than papering over it.
"""

from __future__ import annotations

import re

from arche.workflow._primitive import Detection

# ----------------------------------------------------------------------
# DID detection (W3C decentralized identifiers)
# ----------------------------------------------------------------------

# did:METHOD:IDENTIFIER
# METHOD: lowercase alphanumeric (1-32 chars)
# IDENTIFIER: base58/base64-url/alphanumeric with `.`, `:`, `-`, `_`
_DID_RE = re.compile(
    r"\bdid:([a-z0-9]{1,32}):([A-Za-z0-9._:\-]{4,256})(?![A-Za-z0-9])"
)

# Methods we recognize from the published DID Method registry. Detection
# is shape-based; this dict only sets confidence higher for known methods.
_KNOWN_DID_METHODS: frozenset[str] = frozenset({
    "key",       # did:key — self-describing keys (RFC-style)
    "web",       # did:web — DNS-anchored
    "ion",       # did:ion — Microsoft / Sidetree
    "ethr",      # did:ethr — Ethereum-anchored
    "polygon",   # did:polygon — Polygon-anchored
    "jwk",       # did:jwk — JWK-embedded
    "pkh",       # did:pkh — Public Key Hash
    "indy",      # did:indy — Hyperledger Indy
    "sov",       # did:sov — Sovrin (legacy)
})


def detect_did(text: str) -> list[Detection]:
    """Find W3C DIDs in text.

    Returns list of :class:`Detection` with category ``PII-2-DID``.
    Method name preserved in ``metadata["method"]``.
    """
    detections: list[Detection] = []
    for match in _DID_RE.finditer(text):
        full = match.group(0)
        method = match.group(1)
        identifier = match.group(2)

        # Don't match the literal "did:method:identifier" placeholder
        # if `method` is itself the word "method" — common in documentation
        # examples and would yield false positives.
        if method == "method":
            continue

        confidence = 1.0 if method in _KNOWN_DID_METHODS else 0.7

        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category="PII-2-DID",
            text=full,
            start=match.start(),
            end=match.end(),
            confidence=confidence,
            detector=f"rule:digital_id_did_{method}",
            identity_class="federated",
            metadata={
                "method": method,
                "identifier": identifier,
                "known_method": method in _KNOWN_DID_METHODS,
            },
        ))
    return detections


# ----------------------------------------------------------------------
# Crypto wallet detection
# ----------------------------------------------------------------------

# Bitcoin base58check addresses (P2PKH starts with 1, P2SH with 3).
# Base58 alphabet excludes 0, O, I, l for visual disambiguation.
# Length: 26-34 chars (often 33-34 in practice).
_BTC_BASE58_RE = re.compile(
    r"(?<![A-Za-z0-9])([13][a-km-zA-HJ-NP-Z1-9]{25,34})(?![A-Za-z0-9])"
)

# Bitcoin bech32 (SegWit) addresses. Mainnet: bc1, testnet: tb1.
# Bech32 alphabet: a-z and 0-9 minus 1, b, i, o (canonical: qpzry9x8gf2tvdw0s3jn54khce6mua7l).
# Length: 39-90 chars after the prefix.
_BTC_BECH32_RE = re.compile(
    r"(?<![A-Za-z0-9])((?:bc1|tb1)[a-z0-9]{6,87})(?![A-Za-z0-9])"
)

# Ethereum addresses: 0x + 40 hex characters (case may be mixed for EIP-55).
_ETH_RE = re.compile(
    r"(?<![A-Za-z0-9])(0x[a-fA-F0-9]{40})(?![A-Za-z0-9])"
)


def _eth_eip55_confidence(addr: str) -> float:
    """Heuristic confidence boost for likely EIP-55 mixed-case addresses.

    Pure-lowercase / pure-uppercase: 0.85 (likely valid, no checksum signal).
    Mixed-case: 0.9 (likely EIP-55 intent).
    Full EIP-55 checksum verification is v0.3 work.
    """
    hex_part = addr[2:]
    if hex_part == hex_part.lower() or hex_part == hex_part.upper():
        return 0.85
    return 0.9


def detect_crypto_wallet(text: str) -> list[Detection]:
    """Find Bitcoin (base58 + bech32) and Ethereum wallet addresses.

    Shape-only match in v0.2.0a2 — no full checksum verification.
    Confidence reflects shape distinctiveness, not authenticated validity.
    """
    detections: list[Detection] = []

    # Bitcoin base58check
    for match in _BTC_BASE58_RE.finditer(text):
        addr = match.group(1)
        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category="PII-5-CRYPTO_WALLET",
            text=addr,
            start=match.start(),
            end=match.end(),
            confidence=0.85,
            detector="rule:digital_id_btc_base58",
            identity_class="federated",
            metadata={
                "scheme": "bitcoin",
                "encoding": "base58check",
                "address_type": "P2PKH" if addr[0] == "1" else "P2SH",
            },
        ))

    # Bitcoin bech32 (SegWit)
    for match in _BTC_BECH32_RE.finditer(text):
        addr = match.group(1)
        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category="PII-5-CRYPTO_WALLET",
            text=addr,
            start=match.start(),
            end=match.end(),
            confidence=0.9,
            detector="rule:digital_id_btc_bech32",
            identity_class="federated",
            metadata={
                "scheme": "bitcoin",
                "encoding": "bech32",
                "address_type": "SegWit",
                "network": "mainnet" if addr.startswith("bc1") else "testnet",
            },
        ))

    # Ethereum
    for match in _ETH_RE.finditer(text):
        addr = match.group(1)
        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category="PII-5-CRYPTO_WALLET",
            text=addr,
            start=match.start(),
            end=match.end(),
            confidence=_eth_eip55_confidence(addr),
            detector="rule:digital_id_eth",
            identity_class="federated",
            metadata={
                "scheme": "ethereum",
                "encoding": "hex",
                "checksum_verified": False,  # v0.3 — see TODOS
            },
        ))

    return detections


def detect_digital_ids(text: str) -> list[Detection]:
    """Find all digital identity tokens — DIDs and crypto wallets.

    Equivalent to ``detect_did(text) + detect_crypto_wallet(text)`` but
    returned sorted by character offset for stable downstream processing.
    """
    detections = detect_did(text)
    detections.extend(detect_crypto_wallet(text))
    detections.sort(key=lambda d: d.start)
    return detections


__all__ = ["detect_digital_ids", "detect_did", "detect_crypto_wallet"]
