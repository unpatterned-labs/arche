# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.policy.engine — the v0.2 enforcement engine (PRD §6)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arche.policy import (
    ACTIONS,
    PolicyOutcome,
    Statute,
    apply_policy,
    list_available_statutes,
    load_statute,
)


@dataclass
class _Det:
    """Minimal stand-in for a detection record (matches the duck-typed
    surface the policy engine reads)."""
    start: int
    end: int
    text: str
    category: str


# ── Statute loading ─────────────────────────────────────────────────────────


def test_action_set_is_closed():
    """PRD §6.3: the action set is deliberately closed and small."""
    assert ACTIONS == frozenset({"mask", "tokenize", "drop", "generalize", "audit", "retain"})


def test_available_statutes_includes_ndpa():
    """The base install ships NDPA-2023 (Stage 1 launch statute)."""
    assert "NDPA-2023" in list_available_statutes()


def test_load_statute_ndpa():
    s = load_statute("NDPA-2023")
    assert s.statute_id == "NDPA-2023"
    assert s.jurisdiction == "NG"
    assert s.authority.startswith("Nigeria Data Protection Commission")
    assert s.breach_notification_window_hours == 72
    assert s.policy_mappings  # non-empty


def test_load_statute_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_statute("NOT-A-REAL-STATUTE-2099")


def test_load_statute_caches():
    """Loading the same statute twice should return the cached instance."""
    a = load_statute("NDPA-2023")
    b = load_statute("NDPA-2023")
    assert a is b


def test_statute_action_for_known_category():
    s = load_statute("NDPA-2023")
    action, ref, rationale = s.action_for("PII-2-NIN")
    assert action == "mask"
    assert "NDPA-2023" in ref
    assert rationale  # has a rationale


def test_statute_action_for_unknown_category_falls_back():
    s = load_statute("NDPA-2023")
    action, ref, rationale = s.action_for("PII-9-INVENTED")
    assert action == "mask"  # default_action in the YAML
    assert rationale is None


# ── Action handlers ─────────────────────────────────────────────────────────


def _apply_single(statute, det):
    """Convenience: apply policy to one detection, return (redacted, outcome)."""
    text = "X" * (det.end + 5)
    text = text[:det.start] + det.text + text[det.start + len(det.text):]
    redacted, outcomes = apply_policy(text, [det], statute)
    return redacted, outcomes[0]


def test_action_mask_replaces_with_label():
    s = load_statute("NDPA-2023")
    det = _Det(start=0, end=11, text="12345678901", category="PII-2-NIN")
    text = "12345678901 is the NIN"
    redacted, outcomes = apply_policy(text, [det], s)
    assert outcomes[0].action == "mask"
    assert outcomes[0].applied_value == "[NIN]"
    assert "[NIN]" in redacted
    assert "12345678901" not in redacted


def test_action_tokenize_is_deterministic():
    s = load_statute("NDPA-2023")
    text = "Alice and Alice"
    d1 = _Det(start=0, end=5, text="Alice", category="PII-1-NAME")
    d2 = _Det(start=10, end=15, text="Alice", category="PII-1-NAME")
    _, outcomes = apply_policy(text, [d1, d2], s, tokenize_salt="test")
    assert outcomes[0].action == "tokenize"
    # Same input + same salt -> same token (PRD §6.3 join consistency).
    assert outcomes[0].applied_value == outcomes[1].applied_value
    assert outcomes[0].applied_value.startswith("NAME_")


def test_action_tokenize_salt_changes_output():
    s = load_statute("NDPA-2023")
    text = "Alice"
    det = _Det(start=0, end=5, text="Alice", category="PII-1-NAME")
    _, out_a = apply_policy(text, [det], s, tokenize_salt="org_a")
    _, out_b = apply_policy(text, [det], s, tokenize_salt="org_b")
    # Different deployments -> different tokens (no cross-deployment leak).
    assert out_a[0].applied_value != out_b[0].applied_value


def test_action_drop_removes_span():
    s = load_statute("NDPA-2023")
    text = "Patient has diabetes."
    det = _Det(start=12, end=20, text="diabetes", category="PII-6-HEALTH")
    redacted, outcomes = apply_policy(text, [det], s)
    assert outcomes[0].action == "drop"
    assert outcomes[0].applied_value == ""
    assert "diabetes" not in redacted
    assert redacted == "Patient has ."


def test_action_generalize_year_only_for_dates():
    """``arche.policy._generalize`` collapses YYYY-MM-DD to YYYY."""
    # Construct an ad-hoc statute that maps a category to generalize.
    from arche.policy.engine import _generalize
    assert _generalize("PII-1-DOB", "1985-03-14") == "1985"
    assert _generalize("PII-1-DOB", "1985/03/14") == "1985"


def test_action_generalize_ipv4_truncates_to_24():
    from arche.policy.engine import _generalize
    assert _generalize("PII-8-IP_ADDRESS", "192.168.1.42") == "192.168.1.0/24"


def test_action_retain_leaves_text_untouched():
    s = load_statute("NDPA-2023")
    text = "Acme RC123456 supplies widgets."
    det = _Det(start=5, end=13, text="RC123456", category="PII-2-RC")
    redacted, outcomes = apply_policy(text, [det], s)
    assert outcomes[0].action == "retain"
    assert outcomes[0].applied_value == "RC123456"
    assert redacted == text


# ── Multi-detection processing ──────────────────────────────────────────────


def test_apply_policy_multiple_detections_preserves_order():
    s = load_statute("NDPA-2023")
    text = "Customer Adesola Okonkwo, NIN 12345678901, phone 0803 555 7890."
    detections = [
        _Det(start=9, end=24, text="Adesola Okonkwo", category="PII-1-NAME"),
        _Det(start=30, end=41, text="12345678901", category="PII-2-NIN"),
        _Det(start=49, end=62, text="0803 555 7890", category="PII-3-PHONE"),
    ]
    redacted, outcomes = apply_policy(text, detections, s)

    # Three outcomes, in input order.
    assert len(outcomes) == 3
    assert outcomes[0].category == "PII-1-NAME"
    assert outcomes[1].category == "PII-2-NIN"
    assert outcomes[2].category == "PII-3-PHONE"

    # Substitutions happened.
    assert "12345678901" not in redacted
    assert "0803 555 7890" not in redacted
    assert "[NIN]" in redacted


def test_apply_policy_returns_policy_outcomes():
    s = load_statute("NDPA-2023")
    text = "NIN 12345678901"
    det = _Det(start=4, end=15, text="12345678901", category="PII-2-NIN")
    _, outcomes = apply_policy(text, [det], s)
    assert isinstance(outcomes[0], PolicyOutcome)
    assert outcomes[0].statute_id == "NDPA-2023"
    assert outcomes[0].span == (4, 15)
