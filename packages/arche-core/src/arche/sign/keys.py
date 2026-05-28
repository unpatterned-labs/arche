# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Ed25519 key generation, loading, and ``did:key`` encoding for ``arche.sign``.

Per the verifiability roadmap (locked decisions, 2026-06-02):

- Default signature algorithm: Ed25519.
- Default key identifier: ``did:key`` (self-describing, multibase-encoded
  public key — no infrastructure required to resolve, works offline on
  field devices). PEM supported via load/save helpers.

The did:key spec we implement is the W3C DID Method ``did:key`` v0.7
working draft, using the multicodec prefix ``0xed`` followed by ``0x01``
(varint-encoded as a 2-byte sequence) for Ed25519 public keys, then
base58-btc multibase prefix ``z``.

Trust model: arche is a library, not an issuer. Callers generate and
hold their own keys. arche provides convenience helpers; it never stores
a long-lived key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


# ---------------------------------------------------------------------------
# Multibase / multicodec helpers (did:key)
# ---------------------------------------------------------------------------

# Multicodec varint prefix for Ed25519 public key (0xed) with leading length
# byte (0x01).  See https://github.com/multiformats/multicodec.
_ED25519_MULTICODEC = b"\xed\x01"

# Base58btc alphabet, Bitcoin ordering.
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58btc_encode(data: bytes) -> str:
    """Encode bytes as base58btc (Bitcoin ordering)."""
    # Count leading zero bytes — they map to leading '1' characters.
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))

    # Convert bytes to integer.
    n = int.from_bytes(data, "big")
    chars: list[str] = []
    while n > 0:
        n, remainder = divmod(n, 58)
        chars.append(_BASE58_ALPHABET[remainder])
    encoded = "".join(reversed(chars))
    return "1" * leading_zeros + encoded


def _base58btc_decode(text: str) -> bytes:
    """Decode a base58btc string back to bytes."""
    # Count leading '1' characters → leading zero bytes.
    leading_ones = len(text) - len(text.lstrip("1"))
    n = 0
    for ch in text:
        if ch not in _BASE58_ALPHABET:
            raise ValueError(f"Invalid base58btc character: {ch!r}")
        n = n * 58 + _BASE58_ALPHABET.index(ch)
    decoded = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    return b"\x00" * leading_ones + decoded


def encode_did_key(public_key: Ed25519PublicKey) -> str:
    """Encode an Ed25519 public key as a ``did:key`` identifier.

    Returns a string of the form ``did:key:z6Mk...`` where the suffix is a
    base58btc-encoded multicodec-prefixed public key. This is the
    canonical DID for offline-verifiable Ed25519 keys.
    """
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    payload = _ED25519_MULTICODEC + raw
    return "did:key:z" + _base58btc_encode(payload)


def decode_did_key(did: str) -> Ed25519PublicKey:
    """Decode a ``did:key:z...`` identifier to an Ed25519 public key.

    Raises
    ------
    ValueError
        If the DID isn't a valid did:key for an Ed25519 key.
    """
    if not did.startswith("did:key:z"):
        raise ValueError(f"Not a did:key with base58btc multibase: {did!r}")
    suffix = did[len("did:key:z"):]
    decoded = _base58btc_decode(suffix)
    if not decoded.startswith(_ED25519_MULTICODEC):
        raise ValueError(
            f"did:key is not Ed25519 (expected multicodec prefix "
            f"{_ED25519_MULTICODEC.hex()}, got {decoded[:2].hex()})"
        )
    raw_key = decoded[len(_ED25519_MULTICODEC):]
    if len(raw_key) != 32:
        raise ValueError(
            f"Ed25519 public key must be 32 bytes; got {len(raw_key)}"
        )
    return Ed25519PublicKey.from_public_bytes(raw_key)


# ---------------------------------------------------------------------------
# Keypair container
# ---------------------------------------------------------------------------

@dataclass
class Keypair:
    """An Ed25519 keypair plus its ``did:key`` identifier.

    The ``did_key`` field is the canonical public identifier — share that
    with verifiers. The private key never leaves the holding process.
    """

    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    did_key: str

    def __repr__(self) -> str:  # avoid accidentally printing private key
        return f"Keypair(did_key={self.did_key!r})"

    def public_only(self) -> "Keypair":
        """Return a copy with the private key dropped (for sharing)."""
        # Construct a Keypair-shaped object without exposing a private key.
        # Use a sentinel that raises on use.
        class _NoPrivateKey:
            def __getattr__(self, name: str) -> Any:
                raise RuntimeError(
                    "This Keypair contains only the public key. "
                    "Use the original private-key-bearing keypair to sign."
                )

        return Keypair(
            private_key=_NoPrivateKey(),  # type: ignore[arg-type]
            public_key=self.public_key,
            did_key=self.did_key,
        )


# ---------------------------------------------------------------------------
# Key generation and loading
# ---------------------------------------------------------------------------

def generate_keypair() -> Keypair:
    """Generate a fresh Ed25519 keypair and its did:key identifier.

    Examples
    --------
    >>> kp = generate_keypair()
    >>> kp.did_key.startswith("did:key:z6Mk")
    True
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return Keypair(
        private_key=private_key,
        public_key=public_key,
        did_key=encode_did_key(public_key),
    )


def load_private_key_pem(data: bytes | str, password: bytes | None = None) -> Keypair:
    """Load an Ed25519 private key from PEM-encoded bytes (with optional
    passphrase) and return a Keypair with the did:key derived.

    Raises
    ------
    ValueError
        If the PEM does not contain an Ed25519 private key.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    pk = serialization.load_pem_private_key(data, password=password)
    if not isinstance(pk, Ed25519PrivateKey):
        raise ValueError(
            f"Expected Ed25519PrivateKey from PEM; got {type(pk).__name__}"
        )
    public_key = pk.public_key()
    return Keypair(
        private_key=pk,
        public_key=public_key,
        did_key=encode_did_key(public_key),
    )


def load_public_key(source: str | bytes) -> Ed25519PublicKey:
    """Load a public key from a did:key string, PEM bytes, or raw 32 bytes.

    Examples
    --------
    >>> kp = generate_keypair()
    >>> pk = load_public_key(kp.did_key)
    >>> pk.public_bytes_raw() == kp.public_key.public_bytes_raw()
    True
    """
    if isinstance(source, str):
        if source.startswith("did:key:"):
            return decode_did_key(source)
        # Assume PEM string
        return _load_pem_public(source.encode("utf-8"))
    if isinstance(source, (bytes, bytearray)):
        b = bytes(source)
        if len(b) == 32:
            return Ed25519PublicKey.from_public_bytes(b)
        return _load_pem_public(b)
    raise TypeError(f"Cannot load public key from {type(source).__name__}")


def _load_pem_public(data: bytes) -> Ed25519PublicKey:
    pk = serialization.load_pem_public_key(data)
    if not isinstance(pk, Ed25519PublicKey):
        raise ValueError(
            f"Expected Ed25519PublicKey from PEM; got {type(pk).__name__}"
        )
    return pk


def export_private_pem(keypair: Keypair, password: bytes | None = None) -> bytes:
    """Export the private key to PKCS#8 PEM (optionally encrypted)."""
    encryption: serialization.KeySerializationEncryption
    if password:
        encryption = serialization.BestAvailableEncryption(password)
    else:
        encryption = serialization.NoEncryption()
    return keypair.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )


def export_public_pem(keypair_or_public: Keypair | Ed25519PublicKey) -> bytes:
    """Export the public key to SubjectPublicKeyInfo PEM."""
    pk = (
        keypair_or_public.public_key
        if isinstance(keypair_or_public, Keypair)
        else keypair_or_public
    )
    return pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def save_private_key(keypair: Keypair, path: str | Path, password: bytes | None = None) -> None:
    """Save the private key to disk as encrypted PKCS#8 PEM."""
    Path(path).write_bytes(export_private_pem(keypair, password=password))
