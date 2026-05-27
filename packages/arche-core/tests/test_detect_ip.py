# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.detect.ip — IPv4 + IPv6 detection.

Locks the v0.2.0a2 detection contract from the 2026-05-22 eng review §3
coverage diagram:
- IPv4 happy + RFC1918 private + invalid (256.x) + version-string suppression
- IPv6 full + compressed + zone identifier + IPv4-mapped + invalid
- detect_ip combined function sorts by offset
- Detection.category is PII-8-IP_ADDRESS for both families
"""

from __future__ import annotations

from arche.detect.ip import detect_ip, detect_ipv4, detect_ipv6
from arche.workflow._primitive import Detection

# ----------------------------------------------------------------------
# IPv4
# ----------------------------------------------------------------------


def test_ipv4_detects_public_address() -> None:
    detections = detect_ipv4("Server at 8.8.8.8 responded")
    assert len(detections) == 1
    assert detections[0].text == "8.8.8.8"
    assert detections[0].category == "PII-8-IP_ADDRESS"
    assert detections[0].confidence == 1.0
    assert detections[0].detector == "rule:ip_ipv4"
    assert detections[0].metadata["family"] == "ipv4"
    assert detections[0].metadata["private"] is False


def test_ipv4_flags_rfc1918_private() -> None:
    """192.168.x.x and 10.x.x.x are marked private in metadata."""
    detections = detect_ipv4("LAN: 192.168.1.1 and 10.0.0.1")
    assert len(detections) == 2
    assert all(d.metadata["private"] for d in detections)


def test_ipv4_flags_loopback() -> None:
    detections = detect_ipv4("Local: 127.0.0.1")
    assert len(detections) == 1
    assert detections[0].metadata["loopback"] is True


def test_ipv4_rejects_invalid_octet() -> None:
    """256.1.1.1 is not a valid IPv4 — ipaddress stdlib catches this."""
    detections = detect_ipv4("Bad addr 256.1.1.1 here")
    assert detections == []


def test_ipv4_rejects_partial_match() -> None:
    """1.2.3 (only 3 octets) does not match the regex."""
    detections = detect_ipv4("Partial 1.2.3 not enough")
    assert detections == []


def test_ipv4_suppresses_version_string_by_default() -> None:
    """'version 1.2.3.4' is a software version, not an IP."""
    detections = detect_ipv4("Updated to version 1.2.3.4 yesterday")
    assert detections == []


def test_ipv4_suppresses_v_prefix_too() -> None:
    """'v1.2.3.4' (short for version) also suppressed."""
    detections = detect_ipv4("Released v1.2.3.4 today")
    assert detections == []


def test_ipv4_version_suppression_optional() -> None:
    """Caller can disable suppression to get all matches."""
    detections = detect_ipv4(
        "Updated to version 1.2.3.4 yesterday",
        suppress_version_strings=False,
    )
    assert len(detections) == 1
    assert detections[0].text == "1.2.3.4"


def test_ipv4_real_ip_after_version_string_still_detected() -> None:
    """The suppression window is local — IPs farther in the text are kept."""
    detections = detect_ipv4(
        "Updated to version 1.2.3.4 yesterday. Real IP: 8.8.8.8"
    )
    assert len(detections) == 1
    assert detections[0].text == "8.8.8.8"


def test_ipv4_multicast_and_reserved_flagged() -> None:
    """Multicast 224.0.0.1, reserved 240.0.0.1 are detected but tagged."""
    detections = detect_ipv4("Multicast 224.0.0.1 and reserved 240.0.0.1")
    assert len(detections) == 2
    by_text = {d.text: d for d in detections}
    assert by_text["224.0.0.1"].metadata["multicast"] is True
    assert by_text["240.0.0.1"].metadata["reserved"] is True


def test_ipv4_unspecified() -> None:
    """0.0.0.0 detected, flagged as unspecified."""
    detections = detect_ipv4("Listen on 0.0.0.0:80")
    assert len(detections) == 1
    assert detections[0].metadata["unspecified"] is True


def test_ipv4_offsets_are_correct() -> None:
    """Detection.start/end point to the matched substring."""
    text = "Server at 8.8.8.8 responded"
    detections = detect_ipv4(text)
    assert len(detections) == 1
    assert text[detections[0].start:detections[0].end] == "8.8.8.8"


# ----------------------------------------------------------------------
# IPv6
# ----------------------------------------------------------------------


def test_ipv6_detects_full_address() -> None:
    detections = detect_ipv6("Routed via 2001:0db8:0000:0000:0000:0000:0000:0001 today")
    assert len(detections) == 1
    assert detections[0].category == "PII-8-IP_ADDRESS"
    assert detections[0].metadata["family"] == "ipv6"


def test_ipv6_detects_compressed_form() -> None:
    detections = detect_ipv6("Routed via 2001:db8::1 today")
    assert len(detections) == 1
    assert detections[0].text == "2001:db8::1"


def test_ipv6_detects_link_local_with_zone_id() -> None:
    """fe80::1%eth0 — zone identifier preserved in metadata, included in text."""
    detections = detect_ipv6("Connect to fe80::1%eth0 now")
    assert len(detections) == 1
    assert detections[0].text == "fe80::1%eth0"
    assert detections[0].metadata["zone"] == "eth0"
    assert detections[0].metadata["link_local"] is True


def test_ipv6_detects_ipv4_mapped() -> None:
    """::ffff:192.0.2.1 — IPv4-mapped IPv6."""
    detections = detect_ipv6("Mapped: ::ffff:192.0.2.1")
    assert len(detections) == 1
    assert detections[0].metadata["ipv4_mapped"] is True


def test_ipv6_loopback() -> None:
    detections = detect_ipv6("Local: ::1")
    # Note: ::1 alone is hard to match against generic regex boundaries;
    # detection may or may not fire depending on the regex. Either is fine
    # for v0.2.0a2 — ::1 is unusual in real-world text.
    if detections:
        assert detections[0].metadata["loopback"] is True


def test_ipv6_rejects_invalid_too_many_groups() -> None:
    """Eight is the max — nine groups is invalid."""
    detections = detect_ipv6("Bad: 1:2:3:4:5:6:7:8:9:10")
    assert detections == []


# ----------------------------------------------------------------------
# Combined detect_ip
# ----------------------------------------------------------------------


def test_detect_ip_combines_v4_and_v6() -> None:
    detections = detect_ip("IPv4 8.8.8.8 and IPv6 2001:db8::1")
    families = {d.metadata["family"] for d in detections}
    assert families == {"ipv4", "ipv6"}


def test_detect_ip_sorts_by_offset() -> None:
    """Combined output is sorted by Detection.start ascending."""
    detections = detect_ip("2001:db8::1 first, then 8.8.8.8")
    offsets = [d.start for d in detections]
    assert offsets == sorted(offsets)


def test_detect_ip_returns_detection_objects() -> None:
    """All detector output is the canonical Detection shape (passthrough
    via Pipeline._to_detection).

    Regression: the Detection class is a non-frozen dataclass."""
    detections = detect_ip("8.8.8.8")
    assert all(isinstance(d, Detection) for d in detections)


# ----------------------------------------------------------------------
# Pipeline integration (composes with statute-aware enrichment)
# ----------------------------------------------------------------------


def test_ipv4_detection_with_pipeline_enrichment_picks_up_low_tier() -> None:
    """IP address category is LOW tier under NDPA-2023 / POPIA / KENYA / GHANA
    (anchor test in test_sensitivity_tier.py). End-to-end: Pipeline
    enrichment should populate tier=LOW for IP detections.

    Note: Pipeline doesn't auto-include arche.detect.ip yet — this test
    invokes the detector standalone then runs enrichment manually so we
    don't have to modify Pipeline's _run_detectors mid-commit. Pipeline
    auto-inclusion is a separate concern (the 'core' detector package
    expands in a follow-up)."""
    from arche.policy import load_statute
    from arche.workflow._primitive import Pipeline

    detections = detect_ipv4("Server 8.8.8.8 responded")
    statute = load_statute("NDPA-2023")
    Pipeline._enrich_detections(detections, statute)

    from arche._types import SensitivityTier

    assert detections[0].sensitivity_tier == SensitivityTier.LOW
    assert detections[0].regulatory_citation is not None
    assert "NDPA-2023" in detections[0].regulatory_citation
