"""Tests for PII detection and redaction."""

from arche.protect import detect_pii, redact


def test_detect_phone_pii():
    pii = detect_pii("Call me at +234 803 555 7890")
    assert len(pii) >= 1
    assert any(p.pii_type == "PHONE_NUMBER" for p in pii)


def test_detect_email_pii():
    pii = detect_pii("Email: janet@example.com")
    assert len(pii) >= 1
    assert any("EMAIL" in p.pii_type for p in pii)


def test_detect_nigerian_nin():
    pii = detect_pii("My NIN is 12345678901")
    # Should detect as either phone or NIN pattern
    assert len(pii) >= 1


def test_redact_mask():
    pii = detect_pii("Email: janet@example.com")
    if pii:
        result = redact("Email: janet@example.com", pii, strategy="mask")
        assert "janet@example.com" not in result
        assert "****" in result or "<" in result


def test_redact_placeholder():
    pii = detect_pii("Email: janet@example.com")
    if pii:
        result = redact("Email: janet@example.com", pii, strategy="placeholder")
        assert "janet@example.com" not in result
