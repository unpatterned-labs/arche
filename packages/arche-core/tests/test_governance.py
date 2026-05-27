"""Tests for the governance/compliance module."""

from arche.governance import ComplianceReport, assess_compliance


def test_assess_empty():
    report = assess_compliance()
    assert isinstance(report, ComplianceReport)
    assert report.total_pii_found == 0
    assert report.is_compliant


def test_assess_with_evidence_dicts():
    evidence = [
        {"label": "nin", "text": "12345678901", "country_hint": "NG"},
        {"label": "phone_number", "text": "+2348035557890"},
        {"label": "person", "text": "Fatima Abdullahi"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    assert report.jurisdiction == "NG"
    assert report.total_pii_found >= 2  # nin (high) + phone (medium) + person (low)
    assert report.high_sensitivity_count >= 1  # NIN is high
    assert report.medium_sensitivity_count >= 1  # phone is medium


def test_assess_nigerian_compliance():
    """Nigeria NDPA should be loaded from jurisdiction pack."""
    evidence = [
        {"label": "nin", "text": "12345678901", "country_hint": "NG"},
        {"label": "bvn", "text": "22100987654", "country_hint": "NG"},
        {"label": "email", "text": "test@example.com"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    assert "NDPA" in report.law_name
    assert "NDPC" in report.regulator
    assert report.high_sensitivity_count >= 2  # NIN + BVN


def test_consent_required_for_high_pii():
    evidence = [
        {"label": "nin", "text": "12345678901"},
        {"label": "bvn", "text": "22100987654"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG", consent_obtained=False)
    assert report.consent_status == "required"
    assert any("consent" in a.lower() for a in report.required_actions)


def test_consent_obtained():
    evidence = [{"label": "nin", "text": "12345678901"}]
    report = assess_compliance(evidence=evidence, jurisdiction="NG", consent_obtained=True)
    assert report.consent_status == "obtained"


def test_dpia_required_for_many_high():
    evidence = [
        {"label": "nin", "text": "11111111111"},
        {"label": "bvn", "text": "22222222222"},
        {"label": "national_id", "text": "33333333333"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    assert report.dpia_required


def test_no_dpia_for_low_risk():
    evidence = [
        {"label": "person", "text": "Fatima"},
        {"label": "location", "text": "Lagos"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    assert not report.dpia_required


def test_auto_jurisdiction_inference():
    evidence = [{"label": "nin", "text": "12345678901", "country_hint": "NG"}]
    report = assess_compliance(evidence=evidence, jurisdiction="auto")
    assert report.jurisdiction == "NG"


def test_unknown_jurisdiction_defaults():
    evidence = [{"label": "nin", "text": "12345678901"}]
    report = assess_compliance(evidence=evidence, jurisdiction="XX")
    assert report.jurisdiction == "XX"
    assert report.law_name  # Should have default law name


def test_findings_have_masked_text():
    evidence = [{"label": "nin", "text": "12345678901"}]
    report = assess_compliance(evidence=evidence)
    nin_findings = [f for f in report.findings if f.pii_type == "nin"]
    assert len(nin_findings) >= 1
    assert "***" in nin_findings[0].text_masked


def test_summary_output():
    evidence = [
        {"label": "nin", "text": "12345678901", "country_hint": "NG"},
        {"label": "phone_number", "text": "+2348035557890"},
    ]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    summary = report.summary
    assert "Compliance Report" in summary
    assert "NG" in summary


def test_pii_detections_input():
    pii = [
        {"pii_type": "NIGERIAN_NIN", "text": "12345678901"},
        {"pii_type": "EMAIL", "text": "test@example.com"},
    ]
    report = assess_compliance(pii_detections=pii, jurisdiction="NG")
    assert report.total_pii_found >= 2


def test_cross_border_restriction_for_high():
    evidence = [{"label": "nin", "text": "12345678901", "country_hint": "NG"}]
    report = assess_compliance(evidence=evidence, jurisdiction="NG")
    high_findings = [f for f in report.findings if f.sensitivity == "high"]
    assert len(high_findings) >= 1
    # High-sensitivity PII should have cross-border restriction
    if high_findings:
        assert high_findings[0].cross_border_restriction
