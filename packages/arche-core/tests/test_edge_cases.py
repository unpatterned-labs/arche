"""Edge case and adversarial tests."""

from arche.detect._names.lexicon import are_names_equivalent, normalize_african_name
from arche.extract import Entity, _mask_text, extract


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
