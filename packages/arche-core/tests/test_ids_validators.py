"""Tests for African national ID validators."""

from arche.detect._africa.ids import (
    _validate_bvn,
    _validate_egypt_id,
    _validate_ghana_card,
    _validate_rwanda_nid,
    _validate_sa_id,
    detect_african_ids,
)


def test_sa_id_valid():
    valid, meta = _validate_sa_id("8001015009087")
    assert valid is True
    assert meta["gender"] == "male"
    assert meta["date_of_birth"].startswith("1980")


def test_sa_id_invalid_luhn():
    valid, _ = _validate_sa_id("8001015009080")
    assert valid is False


def test_sa_id_invalid_date():
    valid, _ = _validate_sa_id("8013015009087")  # Month 13
    assert valid is False


def test_egypt_id_valid():
    valid, meta = _validate_egypt_id("29001011234567")
    assert valid is True
    assert meta["date_of_birth"].startswith("1990")


def test_egypt_id_invalid_century():
    valid, _ = _validate_egypt_id("19001011234567")
    assert valid is False


def test_rwanda_nid_valid():
    valid, meta = _validate_rwanda_nid("1199001234567890")
    assert valid is True
    assert meta["birth_year"] == 1990


def test_rwanda_nid_invalid_prefix():
    valid, _ = _validate_rwanda_nid("2199001234567890")
    assert valid is False


def test_bvn_valid():
    valid, _ = _validate_bvn("22100987654")
    assert valid is True


def test_bvn_invalid_prefix():
    valid, _ = _validate_bvn("11100987654")
    assert valid is False


def test_ghana_card_valid():
    valid, _ = _validate_ghana_card("GHA-123456789-0")
    assert valid is True


def test_ghana_card_invalid():
    valid, _ = _validate_ghana_card("GHX-123456789-0")
    assert valid is False


def test_detect_ghana_card_in_text():
    ids = detect_african_ids("Card: GHA-123456789-0")
    gh = [i for i in ids if i.country == "GH"]
    assert len(gh) == 1
    assert gh[0].id_type == "GHANA_CARD"
    assert gh[0].confidence >= 0.90
