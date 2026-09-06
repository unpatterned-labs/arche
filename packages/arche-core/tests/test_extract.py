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


_TWO_ISBNS = ("The book has ISBN 978-1-8063-4245-7 and is also listed under "
              "ISBN 1806342456.")


def test_an_isbn_10_is_not_reread_as_a_south_african_tax_reference():
    # "1806342456" satisfies the ZA tax-reference *format* (ten digits, first
    # digit 0/1/2/3/9) at confidence 0.50; the ISBN-10 check digit has been
    # verified at 0.95. The validated span keeps its digits.
    entities = extract(_TWO_ISBNS, backend="regex")
    isbns = [e for e in entities if e.entity_type == "ISBN"]
    assert [e.metadata["isbn_type"] for e in isbns] == ["ISBN-13", "ISBN-10"]
    ids = [e for e in entities if e.entity_type == "NATIONAL_ID"]
    assert ids == [], ids


def test_the_merge_keeps_both_isbns():
    # `_merge_entities` trusts `source="african"` over everything, which is
    # right for a checksummed NIN against a model guess and was wrong here:
    # with the tax-reference reading present, the ISBN-10 lost the merge.
    from arche.extract import _merge_entities

    merged = _merge_entities([], extract(_TWO_ISBNS, backend="regex"))
    assert sum(e.entity_type == "ISBN" for e in merged) == 2


def test_a_cued_ten_digit_number_reads_as_a_tax_reference():
    for text in ("SARS tax number: 1234567890",
                 "Tax reference 0123456789 (SARS)",
                 "income tax no. 9123456789"):
        entities = extract(text, backend="regex")
        found = [e for e in entities if e.entity_type == "NATIONAL_ID"
                 and e.metadata.get("id_type") == "TAX_REFERENCE"]
        assert len(found) == 1, text
        assert found[0].confidence >= 0.80, text


def test_a_cued_ten_digit_number_reads_as_a_nigerian_tin():
    for text in ("FIRS TIN: 1234567890-0001", "TIN 1234567890"):
        entities = extract(text, backend="regex")
        found = [e for e in entities if e.entity_type == "NATIONAL_ID"
                 and e.metadata.get("id_type") == "TIN"]
        assert len(found) == 1, (text, entities)


def test_a_bare_ten_digit_number_is_not_a_tax_reference():
    # Ten digits is also an order number, an account number and a UK mobile
    # without its leading zero. Without "tax", "TIN", "FIRS" or "SARS" nearby
    # there is no evidence of a tax number -- South African or Nigerian -- so
    # nothing is claimed. Before this, the ZA pattern took any such run at
    # 0.50 and, once it was gated, the NG TIN pattern took it at 0.50 instead.
    for text in ("Order 1234567890 shipped on Monday",
                 "syntax error at 1234567890",   # "tax" inside a word is not a cue
                 "ISBN 1806342456"):
        ids = [e for e in extract(text, backend="regex")
               if e.entity_type == "NATIONAL_ID"]
        assert ids == [], (text, ids)


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
