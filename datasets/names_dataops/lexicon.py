"""Simple lexicon builder: clean, union, dedupe, export."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .schemas import AfricanNameLexiconV1, NormalizedNameV1


def build_lexicon_rows(normalized_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate normalized rows into a deduplicated lexicon."""
    typed_rows = [NormalizedNameV1.model_validate(row) for row in normalized_rows]
    grouped: dict[tuple[str, str], list[NormalizedNameV1]] = defaultdict(list)
    for row in typed_rows:
        key = (row.name_ascii_key, row.name_type)
        grouped[key].append(row)

    out: list[dict[str, Any]] = []
    for (_, _), rows in sorted(grouped.items()):
        best_row = _choose_best_row(rows)
        countries = sorted({r.country_iso2 for r in rows})
        languages = sorted({r.language_tag for r in rows})
        sources = sorted({r.source for r in rows})
        source_ids = sorted({r.source_id for r in rows})
        total_evidence = sum(r.evidence_count for r in rows)
        occurrence_count = len(rows)
        last_seen = max(r.fetched_at for r in rows).isoformat()
        row = AfricanNameLexiconV1(
            name_display=best_row.name_display,
            name_nfc=best_row.name_nfc,
            name_ascii_key=best_row.name_ascii_key,
            name_type=best_row.name_type,
            countries="|".join(countries),
            languages="|".join(languages),
            sources="|".join(sources),
            source_ids="|".join(source_ids),
            total_evidence_count=total_evidence,
            occurrence_count=occurrence_count,
            last_seen_at=last_seen,
        )
        out.append(row.model_dump(mode="json"))

    return sorted(out, key=lambda r: (r["name_type"], r["name_ascii_key"], r["name_nfc"]))


def _choose_best_row(rows: list[NormalizedNameV1]) -> NormalizedNameV1:
    """Pick a stable representative row for a deduped name cluster."""
    scored = sorted(
        rows,
        key=lambda r: (
            -r.evidence_count,
            len(r.name_nfc),
            r.name_nfc.casefold(),
        ),
    )
    return scored[0]


def make_run_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary stats for run metadata."""
    now = datetime.now(UTC).isoformat()
    return {
        "updated_at": now,
        "row_count": len(rows),
        "unique_name_types": sorted({row["name_type"] for row in rows}),
        "unique_countries": sorted(
            {
                c
                for row in rows
                for c in str(row.get("countries", "")).split("|")
                if c
            },
        ),
    }


def build_minimal_unique_rows(lexicon_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Project lexicon rows to a minimal unique-name dataset."""
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for row in lexicon_rows:
        key = (row["name_nfc"], row["name_type"])
        unique[key] = {"name": row["name_nfc"], "name_type": row["name_type"]}
    return [unique[k] for k in sorted(unique.keys(), key=lambda t: (t[1], t[0].casefold()))]
