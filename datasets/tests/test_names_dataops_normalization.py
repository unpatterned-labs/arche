from __future__ import annotations

from datetime import datetime

from datasets.names_dataops.normalize import normalize_name
from datasets.names_dataops.schemas import RawNameEvidenceV1


def _raw(name: str) -> RawNameEvidenceV1:
    return RawNameEvidenceV1(
        source="wikidata",
        source_id="Q1",
        source_license="CC0",
        name_raw=name,
        name_type="given",
        country_iso2="NG",
        language_tag="en",
        evidence_count=1,
        fetched_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )


def test_normalize_diacritics_and_nfc() -> None:
    norm = normalize_name(_raw("  Ad\u00e9y\u1eb9mi  "))
    assert norm.name_display == "Ad\u00e9y\u1eb9mi"
    assert norm.name_nfc == "Ad\u00e9y\u1eb9mi"
    assert norm.name_ascii_key == "adeyemi"
    assert norm.had_diacritics is True


def test_normalize_apostrophe_hyphen_flags() -> None:
    norm = normalize_name(_raw("N'Diaye-Sow"))
    assert norm.contains_apostrophe is True
    assert norm.contains_hyphen is True
    assert norm.name_ascii_key == "ndiayesow"


def test_normalize_strips_wikidata_descriptor_suffixes() -> None:
    norm1 = normalize_name(_raw("Abebe (surname)"))
    norm2 = normalize_name(_raw("Abebe (family name"))
    assert norm1.name_display == "Abebe"
    assert norm2.name_display == "Abebe"
    assert norm1.name_ascii_key == "abebe"
    assert norm2.name_ascii_key == "abebe"
