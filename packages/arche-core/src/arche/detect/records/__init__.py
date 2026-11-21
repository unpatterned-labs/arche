# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Record identifiers: MRNs, health-plan ids, VINs, device ids and URLs.

:func:`detect_record_ids` is the one entry point. It runs
:func:`detect_record_numbers` (label-anchored MRNs, health-plan ids and device
serials; check-digit-validated VINs and IMEIs; MAC addresses) and
:func:`detect_urls` (every URL, flagged ``has_name_or_id_path``).
"""

from __future__ import annotations

from arche.detect.records.ids import detect_record_numbers, vin_check_digit_valid
from arche.detect.records.urls import detect_urls, person_signal
from arche.workflow._primitive import Detection


def detect_record_ids(text: str) -> list[Detection]:
    """MRNs, health-plan ids, VINs, device ids and URLs in ``text``, by offset.

    A record number inside a URL (``/patients/MRN-00482913``) is dropped: the
    URL detection already covers it.
    """
    urls = detect_urls(text)
    ids = [d for d in detect_record_numbers(text)
           if not any(u.start < d.end and d.start < u.end for u in urls)]
    return sorted([*ids, *urls], key=lambda d: d.start)


__all__ = [
    "detect_record_ids", "detect_record_numbers", "detect_urls", "person_signal",
    "vin_check_digit_valid",
]
