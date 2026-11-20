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
        if luhn_valid(m.group(1)) and free(*m.span(1)):
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

__all__ = ["ACCOUNT_CONTEXT", "detect_financial", "iban_valid", "luhn_valid"]
