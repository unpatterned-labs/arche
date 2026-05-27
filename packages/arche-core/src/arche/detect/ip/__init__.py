# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""IP address detection — IPv4 and IPv6.

Public API per the 2026-05-22 detection-first reposition::

    from arche.detect.ip import detect_ip, detect_ipv4, detect_ipv6

    # All IPs (both v4 and v6)
    detections = detect_ip("Server at 8.8.8.8 talks to fe80::1%eth0")

    # Just one family
    v4 = detect_ipv4("192.168.1.1 connected at 2026-05-22T10:00")
    v6 = detect_ipv6("Routed via 2001:db8::1 today")

Cross-cutting (not country-specific) — under the v0.2.0a2 convention,
``arche.detect.ip`` is a **public** module name (not underscore-prefixed)
to mirror discoverability for ``arche.detect.digital_id``. See the
eng review §1 issue 1 decision.

Returns :class:`arche.workflow._primitive.Detection` directly so the
Pipeline normalization step is a passthrough — no NationalID conversion
in between.

Detection rules:

-   IPv4: 4 octets, validated via :mod:`ipaddress` stdlib. Reserved /
    multicast / broadcast addresses are detected but tagged in metadata.
-   IPv6: 16 octets, validated via :mod:`ipaddress`. Zone identifiers
    (``%eth0``) are stripped from the canonical form but preserved in
    metadata. Compressed (``::1``), full, and embedded-v4
    (``::ffff:192.0.2.1``) forms all match.
-   False-positive suppression: matches following the literal substring
    "version" (case-insensitive) within 16 chars are suppressed — common
    in software version strings like "v1.2.3.4 released 2026-01-15."
    Override by passing ``suppress_version_strings=False``.

Category in returned Detection objects: ``PII-8-IP_ADDRESS`` per the
Pan-African PII Taxonomy v0.1. ASN/country enrichment ships behind the
``arche-core[ip]`` extra in a follow-up commit (see TODOS.md #5
ipinfo-db vendoring).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from arche.workflow._primitive import Detection

# IPv4: 4 dot-separated octets. Loose regex; ipaddress validates.
_IPV4_RE = re.compile(
    r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
)

# IPv6: hex groups separated by colons, plus compressed forms. The regex
# is permissive; :class:`ipaddress.IPv6Address` is the source of truth
# for validity. We include an optional zone identifier (``%eth0``).
#
# Pattern excludes lone "::" without flanking hex digits since that
# common shorthand for "all zeros" rarely appears as a real address.
_IPV6_RE = re.compile(
    r"(?<![\w:])"  # boundary: not preceded by word char or colon
    r"("
    # IPv4-mapped FIRST (most specific) — `::ffff:192.0.2.1`. If this
    # alternative isn't first, the engine matches `::ffff:192` via the
    # generic leading-double-colon rule (treating 192 as hex) and the
    # `.0.2.1` suffix gets dropped.
    r"::[Ff]{4}:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}"     # full or short
    r"|(?:[A-Fa-f0-9]{1,4}:){1,6}:[A-Fa-f0-9]{1,4}"    # double-colon middle
    r"|(?:[A-Fa-f0-9]{1,4}:){1,7}:"                     # trailing double-colon
    r"|::(?:[A-Fa-f0-9]{1,4}:){0,6}[A-Fa-f0-9]{1,4}"   # leading double-colon
    r")"
    r"(?:%[A-Za-z0-9._-]+)?"  # optional zone identifier
    r"(?![\w:])"               # boundary: not followed by word char or colon
)

# False-positive guard: when "version" appears within this many chars
# before the match, suppress it. Catches "version 1.2.3.4" and similar.
_VERSION_CONTEXT_CHARS = 16
_VERSION_RE = re.compile(r"\bv(?:ersion)?\b", re.IGNORECASE)


def _is_version_context(text: str, match_start: int) -> bool:
    """Return True if 'version' or 'v' appears within the preceding window."""
    window_start = max(0, match_start - _VERSION_CONTEXT_CHARS)
    preceding = text[window_start:match_start]
    return bool(_VERSION_RE.search(preceding))


def _classify_ipv4(addr: ipaddress.IPv4Address) -> dict[str, Any]:
    """Return metadata dict describing IPv4 reserved-range membership."""
    return {
        "family": "ipv4",
        "private": addr.is_private,
        "loopback": addr.is_loopback,
        "multicast": addr.is_multicast,
        "reserved": addr.is_reserved,
        "link_local": addr.is_link_local,
        "unspecified": addr.is_unspecified,  # 0.0.0.0
    }


def _classify_ipv6(addr: ipaddress.IPv6Address, zone: str | None) -> dict[str, Any]:
    """Return metadata dict describing IPv6 properties + zone identifier."""
    meta: dict[str, Any] = {
        "family": "ipv6",
        "private": addr.is_private,
        "loopback": addr.is_loopback,
        "multicast": addr.is_multicast,
        "reserved": addr.is_reserved,
        "link_local": addr.is_link_local,
        "unspecified": addr.is_unspecified,
        "ipv4_mapped": addr.ipv4_mapped is not None,
    }
    if zone:
        meta["zone"] = zone
    return meta


def detect_ipv4(text: str, *, suppress_version_strings: bool = True) -> list[Detection]:
    """Find IPv4 addresses in text.

    Args:
        text: Free-form input.
        suppress_version_strings: When True (default), matches preceded by
            "version" / "v" within 16 chars are suppressed. Set False to
            include them (e.g. when processing IP-only telemetry where
            version strings won't appear).

    Returns:
        List of :class:`Detection` objects with category
        ``PII-8-IP_ADDRESS``. Confidence is 1.0 for structurally valid
        IPs (the regex pattern matched AND stdlib validation passed).
    """
    detections: list[Detection] = []
    for match in _IPV4_RE.finditer(text):
        raw = match.group(1)
        try:
            addr = ipaddress.IPv4Address(raw)
        except ipaddress.AddressValueError:
            continue  # invalid octet (e.g. 256.1.1.1) — skip

        if suppress_version_strings and _is_version_context(text, match.start()):
            continue

        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category="PII-8-IP_ADDRESS",
            text=raw,
            start=match.start(),
            end=match.end(),
            confidence=1.0,
            detector="rule:ip_ipv4",
            identity_class="inferred",
            metadata=_classify_ipv4(addr),
        ))
    return detections


def detect_ipv6(text: str) -> list[Detection]:
    """Find IPv6 addresses in text.

    Args:
        text: Free-form input.

    Returns:
        List of :class:`Detection` objects with category
        ``PII-8-IP_ADDRESS``. Confidence is 1.0 for structurally valid
        addresses; the zone identifier (``%eth0``) is preserved in
        metadata but stripped from the canonical text.
    """
    detections: list[Detection] = []
    for match in _IPV6_RE.finditer(text):
        raw_with_zone = match.group(0)
        # Split zone identifier (if present)
        if "%" in raw_with_zone:
            addr_str, _, zone = raw_with_zone.partition("%")
        else:
            addr_str, zone = raw_with_zone, None

        try:
            addr = ipaddress.IPv6Address(addr_str)
        except ipaddress.AddressValueError:
            continue

        detections.append(Detection(
            id=f"det:{match.start()}:{match.end()}",
            category="PII-8-IP_ADDRESS",
            text=raw_with_zone,
            start=match.start(),
            end=match.end(),
            confidence=1.0,
            detector="rule:ip_ipv6",
            identity_class="inferred",
            metadata=_classify_ipv6(addr, zone or None),
        ))
    return detections


def detect_ip(
    text: str,
    *,
    suppress_version_strings: bool = True,
) -> list[Detection]:
    """Find both IPv4 and IPv6 addresses in text.

    Equivalent to ``detect_ipv4(text) + detect_ipv6(text)`` but returned
    sorted by character offset for stable downstream processing.

    Args:
        text: Free-form input.
        suppress_version_strings: When True (default), IPv4 matches
            preceded by "version" / "v" within 16 chars are suppressed.
            IPv6 is never suppressed (version strings don't take v6 shape).

    Returns:
        Detections sorted by ``start`` offset.
    """
    detections = detect_ipv4(text, suppress_version_strings=suppress_version_strings)
    detections.extend(detect_ipv6(text))
    detections.sort(key=lambda d: d.start)
    return detections


__all__ = ["detect_ip", "detect_ipv4", "detect_ipv6"]
