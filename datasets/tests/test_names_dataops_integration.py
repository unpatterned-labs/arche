from __future__ import annotations

import csv
from pathlib import Path

import yaml

from datasets.names_dataops.apply import apply_approved_candidates
from datasets.names_dataops.review import write_review_bundle
from datasets.names_dataops.wikidata import fetch_wikidata_rows


def test_fetch_wikidata_rows_with_mock(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_query(**_: object):
        calls["count"] += 1
        if calls["count"] == 1:
            return [
                {
                    "nameEntity": {"value": "http://www.wikidata.org/entity/Q123"},
                    "nameEntityLabel": {"value": "Amina"},
                    "alias": {"value": "Aminah", "xml:lang": "en"},
                },
            ]
        return []

    monkeypatch.setattr("datasets.names_dataops.wikidata._run_query_with_retry", fake_query)
    rows, metadata = fetch_wikidata_rows({"NG": "Q1033"}, page_limit=1, max_pages=1)
    assert len(rows) >= 1
    assert metadata["failed_requests"] == 0
    assert rows[0]["country_iso2"] == "NG"
    assert set(metadata["query_modes"]) == {"person", "entity"}
    assert calls["count"] == 4  # 2 name types x 2 query modes x 1 page


def test_review_transition_and_apply(tmp_path: Path) -> None:
    candidates = [
        {
            "candidate_id": "cand_1",
            "canonical": "Amina",
            "variant": "Aminat",
            "name_type": "given",
            "suggested_tradition": "west_african",
            "confidence": 0.91,
            "evidence_summary": "x",
            "wikidata_qids": ["Q1"],
            "countries": ["NG"],
            "languages": ["en"],
            "status": "approved",
            "source": "wikidata",
            "source_license": "CC0",
            "conflict_flag": False,
            "reviewer_notes": "ok",
        },
    ]
    bundle_dir = tmp_path / "bundle"
    write_review_bundle(candidates, bundle_dir)

    review_csv = bundle_dir / "review_candidates_v1.csv"
    rows = list(csv.DictReader(review_csv.open(encoding="utf-8")))
    assert rows[0]["status"] == "approved"

    yaml_dir = tmp_path / "name_equivalences"
    yaml_dir.mkdir(parents=True)
    with open(yaml_dir / "west_african.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"tradition": "West African", "groups": [{"canonical": "Amina", "variants": []}]},
            f,
            sort_keys=False,
        )

    summary = apply_approved_candidates(
        review_rows=rows,
        yaml_dir=yaml_dir,
        approved_registry_path=tmp_path / "approved_registry_v1.jsonl",
    )
    assert summary["approved"] == 1

    loaded = yaml.safe_load((yaml_dir / "west_african.yaml").read_text(encoding="utf-8"))
    groups = loaded["groups"]
    assert groups[0]["canonical"] == "Amina"
    assert "Aminat" in groups[0]["variants"]
