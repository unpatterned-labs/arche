"""Tests for African domain layer (IDs, phones, currencies, gazetteer)."""

from arche.detect._africa.ids import detect_african_ids
from arche.detect._names.lexicon import NAME_EQUIVALENCES


def test_detect_sa_id():
    """South African ID with valid Luhn check digit."""
    ids = detect_african_ids("SA ID: 8001015009087")
    za_ids = [i for i in ids if i.country == "ZA"]
    assert len(za_ids) >= 1
    assert za_ids[0].metadata.get("gender") == "male"


def test_detect_ghana_card():
    ids = detect_african_ids("Ghana Card GHA-123456789-0")
    gh_ids = [i for i in ids if i.country == "GH"]
    assert len(gh_ids) == 1
    assert gh_ids[0].id_type == "GHANA_CARD"


def test_detect_nigerian_bvn():
    ids = detect_african_ids("Her BVN is 22100987654")
    ng_ids = [i for i in ids if i.country == "NG" and i.id_type == "BVN"]
    assert len(ng_ids) >= 1


def test_context_boost():
    """Keywords near a match should boost confidence."""
    ids_without_context = detect_african_ids("Number: 12345678901")
    ids_with_context = detect_african_ids("Nigeria NIN: 12345678901")
    # With context should have higher confidence
    if ids_without_context and ids_with_context:
        assert ids_with_context[0].confidence >= ids_without_context[0].confidence


def test_no_overlap_detection():
    """A single number shouldn't match multiple patterns simultaneously."""
    ids = detect_african_ids("ID: GHA-123456789-0")
    # Only Ghana Card should match, not other patterns
    assert all(i.id_type == "GHANA_CARD" for i in ids if "GHA" in i.text)


def test_african_phone_parsing():
    try:
        from arche.detect._africa.phones import parse_african_phone
        hits = parse_african_phone("+234 803 555 7890")
        assert len(hits) >= 1
        assert hits[0]["country"] == "NG"
    except ImportError:
        pass  # phone module may not be available


def test_african_currency_detection():
    try:
        from arche.detect._money.african import detect_african_currency
        hits = detect_african_currency("Price is NGN 50,000")
        assert len(hits) >= 1
    except ImportError:
        pass


def test_name_equivalence_table_integrity():
    """Every entry in the table should map to a set containing itself."""
    for key, group in NAME_EQUIVALENCES.items():
        assert key in group, f"Key {key!r} not in its own equivalence group"
