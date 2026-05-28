"""Tests for entity extraction (regex backend)."""

from arche.extract import Entity, extract


def test_extract_nigerian_phone():
    entities = extract("+234 803 555 7890", backend="regex")
    phones = [e for e in entities if e.entity_type == "PHONE"]
    assert len(phones) >= 1
    assert "+234" in phones[0].text


def test_extract_email():
    entities = extract("contact janet@example.com for details", backend="regex")
    emails = [e for e in entities if e.entity_type == "EMAIL"]
    assert len(emails) == 1
    assert emails[0].text == "janet@example.com"
    assert emails[0].confidence >= 0.90


def test_extract_nigerian_nin():
    entities = extract("Her NIN is 12345678901", backend="regex")
    nids = [e for e in entities if e.entity_type == "NATIONAL_ID"]
    assert len(nids) >= 1


def test_extract_date_iso():
    entities = extract("Born on 1990-03-15", backend="regex")
    dates = [e for e in entities if e.entity_type == "DATE"]
    assert len(dates) >= 1
    assert "1990" in dates[0].text


def test_extract_money_naira():
    entities = extract("Salary is NGN 700,000 per month", backend="regex")
    money = [e for e in entities if e.entity_type == "MONEY"]
    assert len(money) >= 1


def test_extract_ghana_card():
    entities = extract("Ghana Card number GHA-123456789-0", backend="regex")
    nids = [e for e in entities if e.entity_type == "NATIONAL_ID"]
    assert len(nids) >= 1
    assert any("GHA" in e.text for e in nids)


def test_extract_auto_falls_back_to_regex():
    """auto backend should gracefully fall back when GliNER is not installed."""
    entities = extract("+234 803 555 7890", backend="auto")
    phones = [e for e in entities if e.entity_type == "PHONE"]
    assert len(phones) >= 1


def test_entity_dataclass():
    e = Entity(text="test", entity_type="PERSON", confidence=0.9, start=0, end=4)
    assert e.source == "regex"
    assert "PERSON" in repr(e)
