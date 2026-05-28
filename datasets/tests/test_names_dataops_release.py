from __future__ import annotations

from pathlib import Path

from datasets import export_hf
from datasets.names_dataops.export import build_enriched_rows, write_dataset_stats
from datasets.names_dataops.io_utils import write_jsonl


def test_legacy_export_has_expected_columns() -> None:
    rows = export_hf.load_all_groups()
    assert rows
    first = rows[0]
    assert list(first.keys()) == ["canonical", "variant", "tradition", "file"]


def test_enriched_export_populates_provenance(tmp_path: Path) -> None:
    legacy_rows = [
        {
            "canonical": "Amina",
            "variant": "Aminat",
            "tradition": "West African",
            "file": "west_african",
        },
    ]
    registry_path = tmp_path / "approved_registry_v1.jsonl"
    write_jsonl(
        registry_path,
        [
            {
                "candidate_id": "cand_1",
                "canonical": "Amina",
                "variant": "Aminat",
                "source": "wikidata",
                "wikidata_qids": ["Q1"],
                "countries": ["NG"],
                "languages": ["en"],
                "confidence": 0.9,
                "applied_at": "2026-01-01T00:00:00+00:00",
            },
        ],
    )
    enriched = build_enriched_rows(legacy_rows, registry_path)
    assert enriched[0]["source"] == "wikidata"
    assert enriched[0]["source_ids"] == "Q1"
    assert enriched[0]["countries"] == "NG"
    assert enriched[0]["languages"] == "en"


def test_dataset_stats_file_written(tmp_path: Path) -> None:
    stats_path = tmp_path / "dataset_stats_v1.json"
    write_dataset_stats(
        legacy_rows=[{"canonical": "Amina", "variant": "Amina", "tradition": "x", "file": "x"}],
        enriched_rows=[
            {
                "canonical": "Amina",
                "variant": "Amina",
                "source": "wikidata",
                "source_ids": "Q1",
            },
        ],
        stats_path=stats_path,
    )
    assert stats_path.exists()
    payload = stats_path.read_text(encoding="utf-8")
    assert "legacy_rows" in payload
