from __future__ import annotations

from datasets.names_dataops.lexicon import build_lexicon_rows


def test_lexicon_unions_and_dedupes() -> None:
    normalized_rows = [
        {
            "source": "wikidata",
            "source_id": "Q1",
            "source_license": "CC0",
            "name_type": "given",
            "country_iso2": "NG",
            "language_tag": "en",
            "evidence_count": 2,
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "name_display": "Amina",
            "name_nfc": "Amina",
            "name_ascii_key": "amina",
            "was_trimmed": False,
            "was_casefolded": True,
            "had_diacritics": False,
            "contains_apostrophe": False,
            "contains_hyphen": False,
            "script": "latin",
        },
        {
            "source": "wikidata",
            "source_id": "Q2",
            "source_license": "CC0",
            "name_type": "given",
            "country_iso2": "GH",
            "language_tag": "en",
            "evidence_count": 3,
            "fetched_at": "2026-01-02T00:00:00+00:00",
            "name_display": "Amina",
            "name_nfc": "Amina",
            "name_ascii_key": "amina",
            "was_trimmed": False,
            "was_casefolded": True,
            "had_diacritics": False,
            "contains_apostrophe": False,
            "contains_hyphen": False,
            "script": "latin",
        },
    ]
    rows = build_lexicon_rows(normalized_rows)
    assert len(rows) == 1
    assert rows[0]["name_nfc"] == "Amina"
    assert rows[0]["countries"] == "GH|NG"
    assert rows[0]["total_evidence_count"] == 5
    assert rows[0]["occurrence_count"] == 2


def test_lexicon_collapses_same_ascii_key_to_single_unique_name() -> None:
    normalized_rows = [
        {
            "source": "wikidata",
            "source_id": "Q1",
            "source_license": "CC0",
            "name_type": "family",
            "country_iso2": "ET",
            "language_tag": "en",
            "evidence_count": 4,
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "name_display": "Abebe",
            "name_nfc": "Abebe",
            "name_ascii_key": "abebe",
            "was_trimmed": False,
            "was_casefolded": True,
            "had_diacritics": False,
            "contains_apostrophe": False,
            "contains_hyphen": False,
            "script": "latin",
        },
        {
            "source": "wikidata",
            "source_id": "Q1",
            "source_license": "CC0",
            "name_type": "family",
            "country_iso2": "ET",
            "language_tag": "en",
            "evidence_count": 1,
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "name_display": "Abebe (surname",
            "name_nfc": "Abebe (surname",
            "name_ascii_key": "abebe",
            "was_trimmed": False,
            "was_casefolded": True,
            "had_diacritics": False,
            "contains_apostrophe": False,
            "contains_hyphen": False,
            "script": "latin",
        },
    ]
    rows = build_lexicon_rows(normalized_rows)
    assert len(rows) == 1
    assert rows[0]["name_nfc"] == "Abebe"
    assert rows[0]["total_evidence_count"] == 5
