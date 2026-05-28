from __future__ import annotations

from pathlib import Path

import yaml

from datasets.names_dataops.candidates import generate_candidates, load_existing_equivalences


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def test_candidate_generation_skips_existing_variant(tmp_path: Path) -> None:
    yaml_dir = tmp_path / "name_equivalences"
    _write_yaml(
        yaml_dir / "west_african.yaml",
        {
            "tradition": "West African",
            "groups": [{"canonical": "Amina", "variants": ["Aminah"]}],
        },
    )
    existing = load_existing_equivalences(yaml_dir)
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
            "name_display": "Aminah",
            "name_nfc": "Aminah",
            "name_ascii_key": "aminah",
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
    ]
    candidates = generate_candidates(normalized_rows, existing)
    assert candidates == []


def test_candidate_generation_creates_pending_row(tmp_path: Path) -> None:
    yaml_dir = tmp_path / "name_equivalences"
    _write_yaml(
        yaml_dir / "cross_linguistic.yaml",
        {
            "tradition": "Cross-linguistic",
            "groups": [{"canonical": "Joseph", "variants": ["Yusuf"]}],
        },
    )
    existing = load_existing_equivalences(yaml_dir)
    normalized_rows = [
        {
            "source": "wikidata",
            "source_id": "Q1",
            "source_license": "CC0",
            "name_type": "given",
            "country_iso2": "NG",
            "language_tag": "en",
            "evidence_count": 5,
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "name_display": "Josef",
            "name_nfc": "Josef",
            "name_ascii_key": "josef",
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
            "country_iso2": "NG",
            "language_tag": "en",
            "evidence_count": 6,
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "name_display": "Joseph",
            "name_nfc": "Joseph",
            "name_ascii_key": "joseph",
            "was_trimmed": False,
            "was_casefolded": True,
            "had_diacritics": False,
            "contains_apostrophe": False,
            "contains_hyphen": False,
            "script": "latin",
        },
    ]
    candidates = generate_candidates(normalized_rows, existing)
    assert len(candidates) == 1
    assert candidates[0]["status"] == "pending"
    assert candidates[0]["canonical"] == "Joseph"
    assert candidates[0]["variant"] == "Josef"
