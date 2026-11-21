# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Bank and card details: IBANs, card numbers, UK sort codes and account numbers.

Every statute pack already governs ``PII-5-BANK_ACCOUNT`` and ``PII-5-CARD``
(UK GDPR masks an account and drops a card; NDPA-2023 likewise), but until now
only a model proposed them, so the rules-only path (``backend="basic"``)
returned "account 12345678 sort code 12-34-56" in the clear. This detector
fills that gap with structure, not guesses:

* **IBAN:** country code, check digits and a body of 11-30 characters, accepted
  only when the ISO 13616 mod-97 check holds. Confidence 1.0.
* **Card number:** 13-19 digits in groups, accepted only when the Luhn check
  holds. Confidence 0.95.
* **Sort code** (UK): six digits as ``NN-NN-NN``, only after the words "sort
  code". Confidence 0.95.
* **Account number:** 8 to 18 digits only after a label ("account", "acct",
  "a/c", "NUBAN", "account number", "account no"): a UK account (8 digits) or a
  Nigerian NUBAN (10 digits) among them. The label is the evidence; a bare
  digit run is never an account. Confidence 0.9.

The label text is never part of the span: ``Account number: 0123456789`` masks to
``Account number: [BANK_ACCOUNT]``.
"""

from __future__ import annotations

import re

from arche.workflow._primitive import Detection

_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?)\b")
_CARD = re.compile(r"(?<![\d-])((?:\d[ -]?){12,18}\d)(?![\d-])")
#: The word just before a number that makes it not a card.
_NOT_A_CARD = re.compile(r"(?i)\b(?:order|invoice|inv|ref|reference|po|sku|model|imei|serial|"
                         r"tracking|isbn)\b[^0-9\n]{0,15}$")
_CARD_CUE = re.compile(r"(?i)\b(?:card|visa|mastercard|amex|credit|debit|pan)\b[^0-9\n]{0,20}$")
_SORT_CODE = re.compile(r"(?i)\bsort[ -]?code\s*:?\s*(\d{2}[- ]?\d{2}[- ]?\d{2})\b")
_ACCOUNT = re.compile(
    r"(?i)\b(?:account|acct|a/c|nuban)(?:\s+(?:no|number|num|#))?\.?\s*(?::|#|-)?\s*"
    r"(\d(?:[ -]?\d){7,17})\b"
)


def iban_valid(raw: str) -> bool:
    """ISO 13616 mod-97: first four characters to the end, letters to numbers,
    remainder 1."""
    s = raw.replace(" ", "").upper()
    if not 15 <= len(s) <= 34 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def luhn_valid(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_shape(raw: str, before: str = "") -> bool:
    """Luhn AND a card's issuer range and length, and no word saying otherwise.

    Luhn alone made any 13-19 digit number a card: every South African ID (13
    digits, Luhn-valid) was also a CARD and, under GDPR, dropped citing
    PCI-DSS; `order 4000123412341234` and `IMEI 490154203237518` were cards
    too (20 Nov 2026). Lengths and first digits by scheme: 16 or 19 starting
    2-6 (Visa, Mastercard, Discover, UnionPay), 15 starting 34/37 (Amex), 14
    starting 36/38 (Diners); 13 (legacy Visa) only after a card word.
    """
    digits = "".join(c for c in raw if c.isdigit())
    if not luhn_valid(digits) or _NOT_A_CARD.search(before):
        return False
    n, head = len(digits), digits[:2]
    if n in (16, 17, 18, 19):
        return digits[0] in "23456"
    if n == 15:
        return head in ("34", "37")
    if n == 14:
        return head in ("36", "38")
    if n == 13:
        return digits[0] == "4" and bool(_CARD_CUE.search(before))
    return False


def _det(kind: str, category: str, m: re.Match[str], group: int, confidence: float,
         detector: str) -> Detection:
    start, end = m.start(group), m.end(group)
    return Detection(
        id=f"det:{kind}:{start}:{end}",
        category=category,
        text=m.group(group),
        start=start,
        end=end,
        confidence=confidence,
        detector=detector,
        identity_class="inferred",
        metadata={"kind": kind},
    )


def detect_financial(text: str) -> list[Detection]:
    """IBANs, card numbers, sort codes and labelled account numbers in ``text``, by offset."""
    out: list[Detection] = []
    taken: list[tuple[int, int]] = []

    def free(s: int, e: int) -> bool:
        return not any(a < e and s < b for a, b in taken)

    for m in _IBAN.finditer(text):
        if iban_valid(m.group(1)):
            out.append(_det("iban", "PII-5-BANK_ACCOUNT", m, 1, 1.0, "rule:iban_mod97"))
            taken.append(m.span(1))
    for m in _SORT_CODE.finditer(text):
        if free(*m.span(1)):
            out.append(_det("sort_code", "PII-5-BANK_ACCOUNT", m, 1, 0.95, "rule:sort_code"))
            taken.append(m.span(1))
    for m in _ACCOUNT.finditer(text):
        digits = sum(c.isdigit() for c in m.group(1))
        if 8 <= digits <= 18 and free(*m.span(1)):
            out.append(_det("account_number", "PII-5-BANK_ACCOUNT", m, 1, 0.9,
                            "rule:account_number"))
            taken.append(m.span(1))
    for m in _CARD.finditer(text):
        if card_shape(m.group(1), text[max(0, m.start(1) - 40):m.start(1)]) \
                and free(*m.span(1)):
            out.append(_det("card", "PII-5-CARD", m, 1, 0.95, "rule:card_luhn"))
            taken.append(m.span(1))
    out.sort(key=lambda d: d.start)
    return out


#: the words that make a following number an account, not a phone (used by
#: arche.detect.phones)
ACCOUNT_CONTEXT = re.compile(
    r"(?i)\b(?:account|acct|a/c|nuban|sort[ -]?code|iban|bvn)\b"
    r"(?:\s+(?:no|number|num|#))?\.?\s*(?::|#|-)?\s*$"
)

__all__ = ["ACCOUNT_CONTEXT", "card_shape", "detect_financial", "iban_valid", "luhn_valid"]
