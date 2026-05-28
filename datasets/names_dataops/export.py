"""Publishing export helpers for legacy + enriched naming datasets."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io_utils import dump_json, read_jsonl, write_csv, write_jsonl
from .schemas import PublishedEquivalenceV1


def build_enriched_rows(
    legacy_rows: list[dict[str, str]],
    approved_registry_path: Path,
) -> list[dict[str, Any]]:
    """Build enriched rows by joining legacy rows with approved provenance."""
    registry_rows = read_jsonl(approved_registry_path)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in registry_rows:
        key = (row.get("canonical", ""), row.get("variant", ""))
        grouped[key].append(row)

    out: list[dict[str, Any]] = []
    for row in legacy_rows:
        key = (row["canonical"], row["variant"])
        provenance = grouped.get(key, [])
        source = sorted({p.get("source", "") for p in provenance if p.get("source")})
        source_ids = sorted(
            {
                qid
                for p in provenance
                for qid in p.get("wikidata_qids", [])
                if isinstance(qid, str) and qid
            },
        )
        countries = sorted(
            {
                c
                for p in provenance
                for c in p.get("countries", [])
                if isinstance(c, str) and c
            },
        )
        languages = sorted(
            {
                language
                for p in provenance
                for language in p.get("languages", [])
                if isinstance(language, str) and language
            },
        )
        confidence = max([p.get("confidence", 0.0) for p in provenance] + [0.0])
        last_seen = max([p.get("applied_at", "") for p in provenance] + [""])
        enriched = PublishedEquivalenceV1(
            canonical=row["canonical"],
            variant=row["variant"],
            tradition=row["tradition"],
            file=row["file"],
            source="|".join(source),
            source_ids="|".join(source_ids),
            countries="|".join(countries),
            languages="|".join(languages),
            confidence=float(confidence),
            last_seen_at=last_seen,
        )
        out.append(enriched.model_dump(mode="json"))
    return out


def write_enriched_exports(
    *,
    enriched_rows: list[dict[str, Any]],
    csv_path: Path,
    jsonl_path: Path,
) -> None:
    """Write enriched exports to CSV + JSONL."""
    if not enriched_rows:
        return
    fieldnames = list(enriched_rows[0].keys())
    write_csv(csv_path, enriched_rows, fieldnames)
    write_jsonl(jsonl_path, enriched_rows)


def write_dataset_stats(
    *,
    legacy_rows: list[dict[str, str]],
    enriched_rows: list[dict[str, Any]],
    stats_path: Path,
) -> None:
    """Write machine-readable stats for dataset card refresh workflows."""
    now = datetime.now(UTC).isoformat()
    payload = {
        "generated_at": now,
        "legacy_rows": len(legacy_rows),
        "legacy_groups": len({row["canonical"] for row in legacy_rows}),
        "legacy_files": sorted({row["file"] for row in legacy_rows}),
        "enriched_rows": len(enriched_rows),
        "rows_with_provenance": sum(
            1 for row in enriched_rows if row.get("source") or row.get("source_ids")
        ),
    }
    dump_json(stats_path, payload)
