# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Check-digit / checksum validators.

These answer one question only: **was this value corrupted** (a typo, a
transposition, an OCR error)? That is *data integrity*, and it is NOT the same
as authenticity. A check digit says nothing about who issued a value or whether
it is real: a forger computes a valid Luhn digit trivially. Authenticity and
non-repudiation live in the cryptography layer (Ed25519 signatures), never here.

So arche only labels a detection ``checksum_valid`` where a value carries a
**publicly-specified** check digit — SA ID (Luhn), ISBN, IBAN (mod-97). National
schemes with no published check-digit algorithm (NIN, BVN, Ghana Card, most TINs)
stay ``format_valid``: we will not invent an algorithm, because a green checkmark
that means nothing is worse than none.

Pure functions, no dependencies. Each returns ``True``/``False``; input cleaning
(stripping spaces/hyphens) is the caller's job unless noted.
"""

from __future__ import annotations


def luhn(digits: str) -> bool:
    """Luhn (mod-10) check. Used by SA ID numbers, payment cards, IMEI.

    Catches all single-digit errors and most adjacent transpositions.
    ``digits`` must be a bare digit string.
    """
    if not digits or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def isbn10(value: str) -> bool:
    """ISBN-10 check (mod-11). The final character may be ``X`` (value 10).

    ``value`` may contain hyphens/spaces; they are ignored.
    """
    core = value.replace("-", "").replace(" ", "").upper()
    if len(core) != 10:
        return False
    total = 0
    for i, ch in enumerate(core):
        if ch == "X" and i == 9:
            n = 10
        elif ch.isdigit():
            n = int(ch)
        else:
            return False
        total += (10 - i) * n
    return total % 11 == 0


def isbn13(value: str) -> bool:
    """ISBN-13 check (mod-10, weights 1/3). Also validates EAN-13 / GTIN-13.

    ``value`` may contain hyphens/spaces; they are ignored.
    """
    core = value.replace("-", "").replace(" ", "")
    if len(core) != 13 or not core.isdigit():
        return False
    total = 0
    for i, ch in enumerate(core):
        total += int(ch) * (1 if i % 2 == 0 else 3)
    return total % 10 == 0


def iban(value: str) -> bool:
    """IBAN check (ISO 13616 / mod-97). Relevant for African IBAN countries
    (e.g. TN, MU, EG). Rearranges, maps letters A=10..Z=35, requires
    ``int % 97 == 1``. ``value`` may contain spaces.
    """
    core = value.replace(" ", "").upper()
    if len(core) < 5 or not core[:2].isalpha() or not core[2:4].isdigit():
        return False
    rearranged = core[4:] + core[:4]
    digits = []
    for ch in rearranged:
        if ch.isdigit():
            digits.append(ch)
        elif ch.isalpha():
            digits.append(str(ord(ch) - 55))  # A->10 ... Z->35
        else:
            return False
    return int("".join(digits)) % 97 == 1
