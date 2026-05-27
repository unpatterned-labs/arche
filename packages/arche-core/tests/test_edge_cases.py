"""Edge case and adversarial tests."""

import pytest
from arche import resolve
from arche.detect._names.lexicon import are_names_equivalent, normalize_african_name
from arche.extract import Entity, _mask_text, extract


def test_resolve_empty_string():
    result = resolve("", backend="regex")
    assert result.entity_count == 0


def test_extract_unicode_input():
    entities = extract("Adéyẹmí Olúwáṣeun 的地址是 Lagos", backend="regex")
    # Should not crash on mixed Unicode
    assert isinstance(entities, list)


def test_normalize_name_unicode():
    result = normalize_african_name("你好")
    assert isinstance(result, str)


def test_names_equivalent_empty():
    ok, score = are_names_equivalent("", "Mohammed")
    assert ok is False
    ok, score = are_names_equivalent("Mohammed", "")
    assert ok is False


def test_over_max_length():
    """Input exceeding max length should raise ValueError."""
    from arche.config import configure, get_config
    old_max = get_config().max_text_length
    configure(max_text_length=100)
    try:
        with pytest.raises(ValueError, match="maximum length"):
            resolve("x" * 200, backend="regex")
    finally:
        configure(max_text_length=old_max)


def test_pii_masked_in_repr():
    """PII-sensitive entities should mask text in repr."""
    e = Entity(text="+234 803 555 7890", entity_type="PHONE",
               confidence=0.9, start=0, end=17)
    r = repr(e)
    assert "+234 803 555 7890" not in r
    assert "+23***" in r


def test_pii_non_sensitive_not_masked():
    """Non-PII entities should show full text in repr."""
    e = Entity(text="Janet Okafor", entity_type="PERSON",
               confidence=0.9, start=0, end=12)
    r = repr(e)
    assert "Janet Okafor" in r


def test_mask_text_helper():
    assert _mask_text("+234 803 555 7890", "PHONE") == "+23***"
    assert _mask_text("janet@example.com", "EMAIL") == "jan***"
    assert _mask_text("Janet Okafor", "PERSON") == "Janet Okafor"
    assert _mask_text("AB", "PHONE") == "AB"  # Too short to mask


def test_sanitize_for_logging():
    result = resolve("Call +234 803 555 7890 about NIN 12345678901", backend="regex")
    safe = result.sanitize_for_logging()
    # Raw text should be masked
    assert "+234" not in safe["text"]
    assert "<input:" in safe["text"]
    # PII entity text should be masked
    for pii in safe.get("pii", []):
        assert "12345678901" not in pii["text"]


def test_redact_output():
    result = resolve(
        "Call +234 803 555 7890",
        backend="regex",
        redact_output=True,
    )
    # The result text should have PII redacted
    assert "+234 803 555 7890" not in result.text
