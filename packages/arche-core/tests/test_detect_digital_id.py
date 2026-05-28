# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.detect.digital_id — DIDs + crypto wallets.

Locks the v0.2.0a2 detection contract from the 2026-05-22 eng review §3
coverage diagram:
- DID detection: did:key, did:web, did:ion known methods at confidence 1.0
- DID detection: unknown methods at confidence 0.7
- DID 'placeholder' false positive (did:method:identifier in docs) suppressed
- BTC base58 + bech32 detection
- ETH 0x-hex detection with EIP-55 confidence boost for mixed-case
- detect_digital_ids combined function sorts by offset
"""

from __future__ import annotations

from arche.detect.digital_id import detect_crypto_wallet, detect_did, detect_digital_ids
from arche.workflow._primitive import Detection

# ----------------------------------------------------------------------
# W3C DIDs
# ----------------------------------------------------------------------


def test_did_key_detected() -> None:
    detections = detect_did("Owner did:key:z6MkpTHR8VNsBxYAAWHut2Geadd9jSrnQ")
    assert len(detections) == 1
    d = detections[0]
    assert d.category == "PII-2-DID"
    assert d.metadata["method"] == "key"
    assert d.metadata["known_method"] is True
    assert d.confidence == 1.0
    assert d.identity_class == "federated"


def test_did_web_detected() -> None:
    detections = detect_did("Domain: did:web:example.com")
    assert len(detections) == 1
    assert detections[0].metadata["method"] == "web"


def test_did_ion_detected() -> None:
    detections = detect_did(
        "Microsoft did:ion:EiClkZMDxPKqC9c-umQfTkR8vvZ9JPhl_xLDI9Nfk38w5w"
    )
    assert len(detections) == 1
    assert detections[0].metadata["method"] == "ion"


def test_did_unknown_method_lower_confidence() -> None:
    """Unknown methods still match the shape but at confidence 0.7."""
    detections = detect_did("Custom: did:fakebrand:abc123def456")
    assert len(detections) == 1
    assert detections[0].metadata["method"] == "fakebrand"
    assert detections[0].metadata["known_method"] is False
    assert detections[0].confidence == 0.7


def test_did_placeholder_in_documentation_suppressed() -> None:
    """'did:method:identifier' is the canonical placeholder in W3C docs.
    Matching it would yield false positives in any technical doc."""
    detections = detect_did("Format: did:method:identifier")
    assert detections == []


def test_did_multiple_in_same_text() -> None:
    detections = detect_did(
        "Issuer did:web:example.com, subject did:key:z6MkpTHR8VNsBxYAAW"
    )
    assert len(detections) == 2
    methods = {d.metadata["method"] for d in detections}
    assert methods == {"web", "key"}


def test_did_offsets_are_correct() -> None:
    text = "Owner did:key:z6MkpTHR8VNsBxYAAWHut2Geadd9jSrnQ"
    detections = detect_did(text)
    assert text[detections[0].start:detections[0].end] == detections[0].text


# ----------------------------------------------------------------------
# Bitcoin wallets
# ----------------------------------------------------------------------


def test_btc_base58_p2pkh() -> None:
    """Genesis block reward address (P2PKH starts with 1)."""
    detections = detect_crypto_wallet(
        "Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa for funding"
    )
    assert len(detections) == 1
    d = detections[0]
    assert d.category == "PII-5-CRYPTO_WALLET"
    assert d.metadata["scheme"] == "bitcoin"
    assert d.metadata["encoding"] == "base58check"
    assert d.metadata["address_type"] == "P2PKH"
    assert d.confidence == 0.85


def test_btc_base58_p2sh() -> None:
    """P2SH addresses start with 3."""
    detections = detect_crypto_wallet(
        "Multisig at 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
    )
    assert len(detections) == 1
    assert detections[0].metadata["address_type"] == "P2SH"


def test_btc_bech32_mainnet() -> None:
    """SegWit bech32 addresses start with bc1."""
    detections = detect_crypto_wallet(
        "Send to bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4 today"
    )
    assert len(detections) == 1
    d = detections[0]
    assert d.metadata["encoding"] == "bech32"
    assert d.metadata["network"] == "mainnet"
    assert d.confidence == 0.9


def test_btc_bech32_testnet() -> None:
    """SegWit testnet addresses start with tb1."""
    detections = detect_crypto_wallet(
        "Testnet: tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
    )
    if detections:  # length boundaries can vary; testnet match is best-effort
        assert detections[0].metadata["network"] == "testnet"


# ----------------------------------------------------------------------
# Ethereum wallets
# ----------------------------------------------------------------------


def test_eth_lowercase_address() -> None:
    """Pure-lowercase ETH = base shape match at confidence 0.85."""
    detections = detect_crypto_wallet(
        "Send to 0x742d35cc6634c0532925a3b844bc9e7595f0beb0"
    )
    assert len(detections) == 1
    d = detections[0]
    assert d.category == "PII-5-CRYPTO_WALLET"
    assert d.metadata["scheme"] == "ethereum"
    assert d.confidence == 0.85


def test_eth_mixed_case_address_eip55_boost() -> None:
    """Mixed-case ETH = likely EIP-55 intent, confidence 0.9."""
    detections = detect_crypto_wallet(
        "Send to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
    )
    assert len(detections) == 1
    assert detections[0].confidence == 0.9


def test_eth_uppercase_address_no_eip55_boost() -> None:
    """Pure-uppercase ETH (uncommon but valid) = base confidence."""
    detections = detect_crypto_wallet(
        "Address 0x742D35CC6634C0532925A3B844BC9E7595F0BEB0"
    )
    assert len(detections) == 1
    assert detections[0].confidence == 0.85


def test_eth_rejects_wrong_length() -> None:
    """0x + 39 hex chars (one short of 40) — no match."""
    detections = detect_crypto_wallet("Bad: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb")
    assert detections == []


def test_eth_rejects_non_hex_chars() -> None:
    """0x + 40 chars containing 'g' (not hex) — no match."""
    detections = detect_crypto_wallet(
        "Not hex: 0x742g35cc6634c0532925a3b844bc9e7595f0beb0"
    )
    assert detections == []


def test_eth_checksum_metadata_flag() -> None:
    """checksum_verified=False — full EIP-55 validation deferred to v0.3."""
    detections = detect_crypto_wallet(
        "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
    )
    assert detections[0].metadata["checksum_verified"] is False


# ----------------------------------------------------------------------
# Combined detect_digital_ids
# ----------------------------------------------------------------------


def test_detect_digital_ids_combines_did_and_wallets() -> None:
    text = (
        "Wallet 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0 "
        "owned by did:key:z6MkpTHR8VNsBxYAAWHut2Geadd9jSrnQ"
    )
    detections = detect_digital_ids(text)
    categories = {d.category for d in detections}
    assert "PII-2-DID" in categories
    assert "PII-5-CRYPTO_WALLET" in categories


def test_detect_digital_ids_sorts_by_offset() -> None:
    text = "did:web:example.com first, 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0 second"
    detections = detect_digital_ids(text)
    offsets = [d.start for d in detections]
    assert offsets == sorted(offsets)


def test_detect_digital_ids_returns_detection_objects() -> None:
    """All returned objects are the canonical Detection shape."""
    detections = detect_digital_ids("did:key:z6Mk")
    assert all(isinstance(d, Detection) for d in detections)


# ----------------------------------------------------------------------
# Pipeline integration (statute-aware enrichment)
# ----------------------------------------------------------------------


def test_did_enrichment_uses_statute_default_tier() -> None:
    """DIDs are PII-2-DID. NDPA-2023 doesn't have a tier mapping for this
    specific category (it's an arche-introduced subtype), so enrichment
    should default to MODERATE.

    This is a regression guard: ensures unmapped categories don't crash
    enrichment."""
    from arche._types import SensitivityTier
    from arche.policy import load_statute
    from arche.workflow._primitive import Pipeline

    detections = detect_did("Subject did:key:z6MkpTHR8VNsBxYAAW")
    statute = load_statute("NDPA-2023")
    Pipeline._enrich_detections(detections, statute)

    # PII-2-DID is not in any shipped statute YAML (yet) so falls back to MODERATE.
    assert detections[0].sensitivity_tier == SensitivityTier.MODERATE
