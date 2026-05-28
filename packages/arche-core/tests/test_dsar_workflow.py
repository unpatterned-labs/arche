# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Tests for arche.workflow.dsar — citizen-side DSAR draft workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arche.sign import VerifyExtractWorkflow, generate_keypair
from arche.workflow import (
    DSAROrganization,
    DSARRequestor,
    DSARWorkflow,
)


# ── Configuration / validation ──────────────────────────────────────────────


def _kp():
    return generate_keypair()


def _requestor():
    return DSARRequestor(
        name="Adesola Okonkwo",
        identifier_label="NIN",
        identifier_value="12345678901",
        email="adesola@example.com",
        phone="+234 803 555 7890",
    )


def _targets():
    return [DSAROrganization(name="Sterling Bank", dpo_email="dpo@sterlingbank.ng")]


def test_dsar_workflow_requires_supported_statute():
    with pytest.raises(ValueError, match="Unsupported statute"):
        DSARWorkflow(
            jurisdiction="NG",
            statute="NOT-A-REAL-STATUTE",
            requestor=_requestor(),
            request_type="access",
            targets=_targets(),
        )


def test_dsar_workflow_requires_known_request_type():
    with pytest.raises(ValueError, match="Unsupported request_type"):
        DSARWorkflow(
            jurisdiction="NG",
            requestor=_requestor(),
            request_type="invented",  # type: ignore[arg-type]
            targets=_targets(),
        )


def test_dsar_workflow_requires_at_least_one_target():
    with pytest.raises(ValueError, match="target organization"):
        DSARWorkflow(
            jurisdiction="NG",
            requestor=_requestor(),
            request_type="access",
            targets=[],
        )


def test_dsar_workflow_rejects_non_draft_dispatch():
    """Stage 1 only supports draft_only per PRD §15.3."""
    with pytest.raises(ValueError, match="draft_only"):
        DSARWorkflow(
            jurisdiction="NG",
            requestor=_requestor(),
            request_type="access",
            targets=_targets(),
            dispatch_mode="auto_dispatch",  # type: ignore[arg-type]
        )


def test_dsar_workflow_infers_statute_from_jurisdiction():
    wf = DSARWorkflow(
        jurisdiction="NG",
        requestor=_requestor(),
        request_type="access",
        targets=_targets(),
    )
    assert wf.statute == "NDPA-2023"


def test_dsar_workflow_describe():
    wf = DSARWorkflow(
        jurisdiction="ZA",
        requestor=_requestor(),
        request_type="erasure",
        targets=_targets(),
    )
    d = wf.describe()
    assert d["kind"] == "DSARWorkflow"
    assert d["statute"] == "POPIA"
    assert d["request_type"] == "erasure"
    assert d["dispatch_mode"] == "draft_only"


# ── Letter rendering ────────────────────────────────────────────────────────


def test_dsar_run_emits_one_draft_per_target():
    wf = DSARWorkflow(
        jurisdiction="NG",
        requestor=_requestor(),
        request_type="access",
        targets=[
            DSAROrganization(name="Sterling Bank", dpo_email="dpo@sterlingbank.ng"),
            DSAROrganization(name="MTN Nigeria", dpo_email="dpo@mtn.ng"),
        ],
    )
    result = wf.run(_kp())
    assert len(result.drafts) == 2
    assert result.drafts[0].target.name == "Sterling Bank"
    assert result.drafts[1].target.name == "MTN Nigeria"


def test_dsar_letter_cites_correct_ndpa_section_for_access():
    wf = DSARWorkflow(
        jurisdiction="NG",
        requestor=_requestor(),
        request_type="access",
        targets=_targets(),
    )
    result = wf.run(_kp())
    letter = result.drafts[0].letter_text
    assert "NDPA-2023 s.34" in letter
    assert "Sterling Bank" in letter
    assert "Adesola Okonkwo" in letter
    assert "NIN" in letter
    assert "12345678901" in letter


def test_dsar_letter_cites_correct_ndpa_section_for_erasure():
    wf = DSARWorkflow(
        jurisdiction="NG",
        requestor=_requestor(),
        request_type="erasure",
        targets=_targets(),
    )
    result = wf.run(_kp())
    letter = result.drafts[0].letter_text
    assert "NDPA-2023 s.36" in letter
    assert "Erasure" in letter or "erasure" in letter


def test_dsar_letter_cites_popia_for_za_jurisdiction():
    wf = DSARWorkflow(
        jurisdiction="ZA",
        requestor=DSARRequestor(
            name="Thabo Mokoena",
            identifier_label="SA ID",
            identifier_value="8001015009087",
        ),
        request_type="access",
        targets=[DSAROrganization(name="Standard Bank")],
    )
    result = wf.run(_kp())
    letter = result.drafts[0].letter_text
    assert "POPIA s.23" in letter
    assert "Information Regulator" in letter


def test_dsar_letter_cites_kenya_dpa_for_ke():
    wf = DSARWorkflow(
        jurisdiction="KE",
        requestor=DSARRequestor(
            name="Wanjiru Kamau",
            identifier_label="Kenya ID",
            identifier_value="22345678",
        ),
        request_type="access",
        targets=[DSAROrganization(name="Safaricom")],
    )
    result = wf.run(_kp())
    letter = result.drafts[0].letter_text
    assert "Kenya DPA s.26" in letter
    assert "Office of the Data Protection Commissioner" in letter


def test_dsar_letter_cites_ghana_dpa_for_gh():
    wf = DSARWorkflow(
        jurisdiction="GH",
        requestor=DSARRequestor(
            name="Kofi Mensah",
            identifier_label="Ghana Card",
            identifier_value="GHA-123456789-0",
        ),
        request_type="access",
        targets=[DSAROrganization(name="MTN Ghana")],
    )
    result = wf.run(_kp())
    letter = result.drafts[0].letter_text
    assert "Ghana DPA s.35" in letter
    assert "Data Protection Commission" in letter


def test_dsar_uses_statute_default_deadline_when_not_overridden():
    # NDPA / POPIA / Kenya DPA = 30 days; Ghana DPA = 21 days
    wf_ng = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="access", targets=_targets(),
    )
    assert wf_ng.deadline_days == 30

    wf_gh = DSARWorkflow(
        jurisdiction="GH",
        requestor=DSARRequestor(name="x", identifier_label="Ghana Card",
                                identifier_value="GHA-000000000-0"),
        request_type="access",
        targets=[DSAROrganization(name="x")],
    )
    assert wf_gh.deadline_days == 21


def test_dsar_caller_can_override_deadline():
    wf = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="access", targets=_targets(),
        deadline_days=14,
    )
    assert wf.deadline_days == 14


# ── Signed envelope integration ─────────────────────────────────────────────


def test_dsar_draft_has_signed_envelope():
    """Every draft carries a JWS-signed envelope per the verifiability roadmap."""
    wf = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="access", targets=_targets(),
    )
    result = wf.run(_kp())
    envelope = result.drafts[0].signed_envelope
    assert envelope.count(".") == 2   # JWS compact form has 3 segments
    assert envelope.startswith("eyJ")  # base64url-encoded JOSE header


def test_dsar_envelope_carries_correct_purpose():
    """The envelope's purpose field encodes the DSAR request type."""
    kp = _kp()
    wf = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="erasure", targets=_targets(),
    )
    result = wf.run(kp)
    envelope = result.drafts[0].signed_envelope

    verified = VerifyExtractWorkflow().process(envelope)
    assert verified.signature_valid is True
    assert verified.envelope.purpose == "dsar_erasure"


def test_dsar_envelope_signed_by_citizen_key():
    """The signature is the citizen's, not arche's. did:key resolves offline."""
    kp = _kp()
    wf = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="access", targets=_targets(),
    )
    result = wf.run(kp)
    verified = VerifyExtractWorkflow().process(result.drafts[0].signed_envelope)
    assert verified.signature_valid is True
    assert verified.issuer_did == kp.did_key


def test_dsar_envelope_has_expiry_matching_deadline():
    """``expires_at`` on the envelope reflects the statutory deadline."""
    kp = _kp()
    wf = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="access", targets=_targets(),
        deadline_days=30,
    )
    before = datetime.now(timezone.utc)
    result = wf.run(kp)
    after = datetime.now(timezone.utc)

    verified = VerifyExtractWorkflow().process(result.drafts[0].signed_envelope)
    expires = datetime.fromisoformat(verified.envelope.expires_at)
    # Should be roughly 30 days from "now"
    delta = expires - before
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, hours=1)


def test_dsar_result_metadata():
    wf = DSARWorkflow(
        jurisdiction="NG", requestor=_requestor(),
        request_type="rectification", targets=_targets(),
    )
    result = wf.run(_kp())
    assert result.request_type == "rectification"
    assert result.jurisdiction == "NG"
    assert result.statute == "NDPA-2023"
    assert result.dispatch_mode == "draft_only"
    # Stage 1 doesn't dispatch
    assert result.sent_at == [None]
    assert result.tracking == [None]
