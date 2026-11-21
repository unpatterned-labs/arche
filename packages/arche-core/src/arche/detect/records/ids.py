# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Record identifiers: medical record numbers, health-plan ids, VINs, device ids.

HIPAA Safe Harbor lists each of these as an identifier to remove (45 CFR
§164.514(b)(2)(i)(H), (I), (L), (M)), and every other pack treats them as
personal data when they point at a person. The shapes are not distinctive (an
MRN is "some digits"), so every rule but two is anchored on the label in front
of the value; the label is the evidence, and it is never part of the span:

* **MRN** (``PII-2-MRN``): only after "MRN", "medical record (no|number)",
  "hospital (no|number)", "patient (id|no|number)", "UR number".
* **Health-plan / member id** (``PII-2-HEALTH_PLAN_ID``): only after "member
  (id|no|number)", "health plan (id|no|number)", "policy (no|number)",
  "insurance (id|no|number)", "medical aid (no|number)", "NHIS (no|number)",
  "Medicare/Medicaid (id|no|number)", "subscriber/beneficiary id".
* **VIN** (``PII-8-VEHICLE_ID``): 17 characters from the ISO 3779 alphabet (no
  I, O or Q). Without a label it must pass the North American check digit at
  position 9 (49 CFR §565.15) and carry a valid model-year code at position 10.
  After "VIN", "vehicle identification number" or "chassis number" a VIN that
  fails the check is still accepted (non-North-American VINs carry no check
  digit), flagged ``check_digit_valid: False``.
* **Device id** (``PII-8-DEVICE_ID``): a serial only after "serial", "S/N",
  "SN", "device id", "UDI"; an IMEI only after "IMEI" and only when its Luhn
  digit holds; a MAC address by shape (six hex pairs, ``:`` or ``-``).

A value must hold at least three digits (a serial: two, and five characters),
and not be all zeros, so "MRN pending", "serial killer" and an SSN's "serial
0000" never match.
"""

from __future__ import annotations

import re

from arche.detect._checksum import luhn
from arche.workflow._primitive import Detection

#: an identifier value: starts and ends alphanumeric, may hold / - . inside
_VALUE = r"([A-Za-z0-9](?:[A-Za-z0-9/\-.]{1,28}[A-Za-z0-9])?)"
_NUM = r"(?:\s+(?:no|number|num|nr|id|#))?"
_SEP = r"\.?\s*(?:[:#=-]\s*)?"

_MRN = re.compile(
    r"(?i)\b(?:MRN|medical\s+record(?:\s+(?:no|number|num|#))?|"
    r"hospital\s+(?:no|number|num|#)|patient\s+(?:id|no|number|num|#)|"
    r"UR\s+(?:no|number))" + _SEP + _VALUE
)
_HEALTH_PLAN = re.compile(
    r"(?i)\b(?:(?:member(?:ship)?|subscriber|beneficiary|enrol+ee)\s+(?:id|no|number|num|#)|"
    r"health[\s-]*plan(?:\s+(?:id|no|number|num|#))+|"
    r"(?:insurance|insurer)\s+(?:id|no|number|num|#)|policy\s+(?:no|number|num|#)|"
    r"medical\s+aid(?:\s+(?:membership|member))?" + _NUM + r"|"
    r"NHIS" + _NUM + r"|medic(?:are|aid)" + _NUM + r")" + _SEP + _VALUE
)
_VIN = re.compile(r"(?<![A-Za-z0-9-])([A-HJ-NPR-Z0-9]{17})(?![A-Za-z0-9-])")
_VIN_CUE = re.compile(
    r"(?i)\b(?:VIN|vehicle\s+identification(?:\s+(?:no|number))?|chassis(?:\s+(?:no|number))?)"
    r"\.?\s*(?:[:#-]\s*)?$"
)
_SERIAL = re.compile(
    r"(?:(?i:\bserial(?:\s+(?:no|number|num|#))?)|\bS/N|\bSN\b|(?i:\bdevice\s+(?:id|identifier|"
    r"serial))|\bUDI)" + _SEP +
    # optional letters-only model prefix ("PM-SN 88123-XZ") when a value follows
    r"((?:[A-Z]{1,5}(?:-[A-Z]{1,5})?\s+(?=[A-Z0-9-]*\d))?"
    r"[A-Za-z0-9](?:[A-Za-z0-9/\-.]{1,28}[A-Za-z0-9])?)"
)
_IMEI = re.compile(
    r"(?i)\bIMEI(?:\s+(?:no|number|#))?" + _SEP +
    r"(\d{2}[ -]?\d{6}[ -]?\d{6}[ -]?\d)(?![\d-])"
)
_MAC = re.compile(r"(?<![0-9A-Fa-f:-])((?:[0-9A-Fa-f]{2}([:-]))(?:[0-9A-Fa-f]{2}\2){4}"
                  r"[0-9A-Fa-f]{2})(?![0-9A-Fa-f:-])")

_VIN_VALUES = {**{str(d): d for d in range(10)},
               **dict(zip("ABCDEFGH", range(1, 9), strict=True)),
               **dict(zip("JKLMN", range(1, 6), strict=True)), "P": 7, "R": 9,
               **dict(zip("STUVWXYZ", range(2, 10), strict=True))}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
#: model-year codes at position 10 (no I, O, Q, U, Z or 0)
_VIN_YEARS = set("ABCDEFGHJKLMNPRSTVWXY123456789")


def vin_check_digit_valid(vin: str) -> bool:
    """North American VIN check digit (49 CFR §565.15): weighted sum mod 11 at
    position 9, ``X`` for 10."""
    vin = vin.upper()
    if len(vin) != 17 or any(c not in _VIN_VALUES for c in vin):
        return False
    total = sum(_VIN_VALUES[c] * w for c, w in zip(vin, _VIN_WEIGHTS, strict=True))
    r = total % 11
    return vin[8] == ("X" if r == 10 else str(r))


def _det(kind: str, category: str, value: str, start: int, confidence: float,
         detector: str, **meta: object) -> Detection:
    end = start + len(value)
    return Detection(
        id=f"det:{kind}:{start}:{end}",
        category=category,
        text=value,
        start=start,
        end=end,
        confidence=confidence,
        detector=detector,
        identity_class="inferred",
        metadata={"kind": kind, **meta},
    )


def _value(m: re.Match[str], group: int = 1) -> tuple[str, int]:
    """The captured value with trailing punctuation removed, and its start."""
    v = m.group(group).rstrip(".-/")
    return v, m.start(group)


def detect_record_numbers(text: str) -> list[Detection]:
    """MRNs, health-plan ids, VINs and device ids in ``text``, by offset.

    URLs are :func:`arche.detect.records.urls.detect_urls`;
    :func:`arche.detect.records.detect_record_ids` runs both.
    """
    out: list[Detection] = []
    taken: list[tuple[int, int]] = []

    def add(d: Detection) -> None:
        if not any(a < d.end and d.start < b for a, b in taken):
            out.append(d)
            taken.append((d.start, d.end))

    for m in _IMEI.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if luhn(digits):
            add(_det("imei", "PII-8-DEVICE_ID", m.group(1), m.start(1), 0.95, "rule:imei_luhn",
                     check_digit_valid=True, cue="IMEI"))
    for m in _MAC.finditer(text):
        add(_det("mac_address", "PII-8-DEVICE_ID", m.group(1), m.start(1), 0.9,
                 "rule:mac_address"))
    for m in _VIN.finditer(text):
        vin = m.group(1)
        if vin.isdigit() or vin.isalpha():
            continue
        cue = bool(_VIN_CUE.search(text[max(0, m.start(1) - 40):m.start(1)]))
        valid = vin_check_digit_valid(vin)
        if valid and (cue or vin[9] in _VIN_YEARS):
            add(_det("vin", "PII-8-VEHICLE_ID", vin, m.start(1), 1.0 if cue else 0.9,
                     "rule:vin_check_digit", check_digit_valid=True, labelled=cue))
        elif cue:
            add(_det("vin", "PII-8-VEHICLE_ID", vin, m.start(1), 0.85, "rule:vin_labelled",
                     check_digit_valid=False, labelled=True))
    for pattern, kind, category, detector, min_digits in (
        (_MRN, "mrn", "PII-2-MRN", "rule:mrn_labelled", 3),
        (_HEALTH_PLAN, "health_plan_id", "PII-2-HEALTH_PLAN_ID", "rule:health_plan_labelled", 3),
        (_SERIAL, "device_serial", "PII-8-DEVICE_ID", "rule:device_serial_labelled", 2),
    ):
        for m in pattern.finditer(text):
            value, start = _value(m)
            digits = [c for c in value if c.isdigit()]
            if len(digits) < min_digits or set(value) <= {"0", "-", "/", "."}:
                continue
            if kind == "device_serial" and len(value) < 5:
                continue
            label = text[m.start():m.start(1)].strip(" :#=-.")
            add(_det(kind, category, value, start, 0.9, detector, cue=label))
    out.sort(key=lambda d: d.start)
    return out


__all__ = ["detect_record_numbers", "vin_check_digit_valid"]
