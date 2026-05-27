"""Review bundle creation helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .io_utils import ensure_parent, write_csv
from .schemas import CandidateEquivalenceV1


def write_review_bundle(candidates: list[dict[str, Any]], bundle_dir: Path) -> dict[str, int]:
    """Write main and per-status review artifacts."""
    typed = [
        CandidateEquivalenceV1.model_validate(row).model_dump(mode="json")
        for row in candidates
    ]
    typed_sorted = sorted(typed, key=lambda row: row["candidate_id"])
    fieldnames = list(typed_sorted[0].keys()) if typed_sorted else list(
        CandidateEquivalenceV1.model_fields.keys()
    )

    ensure_parent(bundle_dir / "placeholder")
    main_path = bundle_dir / "review_candidates_v1.csv"
    write_csv(main_path, typed_sorted, fieldnames)

    status_counter = Counter(row["status"] for row in typed_sorted)
    for status in ("pending", "approved", "rejected"):
        subset = [row for row in typed_sorted if row["status"] == status]
        write_csv(bundle_dir / f"{status}_candidates_v1.csv", subset, fieldnames)

    summary_path = bundle_dir / "summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Review Bundle Summary\n\n")
        f.write(f"- Total candidates: {len(typed_sorted)}\n")
        f.write(f"- Pending: {status_counter.get('pending', 0)}\n")
        f.write(f"- Approved: {status_counter.get('approved', 0)}\n")
        f.write(f"- Rejected: {status_counter.get('rejected', 0)}\n")
        conflict_count = sum(1 for row in typed_sorted if row.get("conflict_flag"))
        f.write(f"- Conflict flagged: {conflict_count}\n")

    return {
        "total": len(typed_sorted),
        "pending": status_counter.get("pending", 0),
        "approved": status_counter.get("approved", 0),
        "rejected": status_counter.get("rejected", 0),
    }
