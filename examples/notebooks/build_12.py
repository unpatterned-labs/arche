# SPDX-License-Identifier: Apache-2.0
"""Generate 12_review_feedback_and_evaluation.ipynb.

Run from the repository root:

    uv run --package arche-core python examples/notebooks/build_12.py
"""
from __future__ import annotations

import json
from pathlib import Path

MARKDOWN, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def markdown(text: str) -> None:
    cells.append((MARKDOWN, text.strip("\n")))


def code(text: str) -> None:
    cells.append((CODE, text.strip("\n")))


markdown("""
# From review to an evaluation report

This notebook demonstrates Arche's alpha feedback loop for a two-list
crosswalk:

1. Run the matcher and retain its evidence and pins.
2. Capture an accountable human outcome for a `review` edge.
3. Use complete labels to measure automatic-match quality and review cost.

It uses two small facility examples. The workflow is real; the data is too
small to support any accuracy claim.
""")

markdown("""
## Setup

Run from the repository root or another directory inside this checkout.
""")

code("""
import json
import sys
from pathlib import Path

REPO = Path.cwd().resolve()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent

if not (REPO / "packages" / "arche-core").exists():
    raise RuntimeError("Run this notebook from inside the arche repository.")

sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import crosswalk
from arche.resolve.metrics import evaluate
""")

markdown("""
## Run a crosswalk

Both pairs have identical names and are 4.45 km apart. The rare facility name
clears the distinctive-evidence gate. The generic name remains in `review`.
""")

code("""
registry = [
    {"id": "facility-001", "name": "Gyaranya Health Post", "lat": 11.90, "lon": 8.50},
    {"id": "facility-002", "name": "General Hospital", "lat": 12.00, "lon": 8.50},
]
survey = [
    {"id": "osm-101", "name": "Gyaranya Health Post", "lat": 11.94, "lon": 8.50},
    {"id": "osm-102", "name": "General Hospital", "lat": 12.04, "lon": 8.50},
]

result = crosswalk(registry, survey, entity="place", block=None)
for edge in result["matches"]:
    print(edge["a_id"], edge["b_id"], edge["decision"], edge["score"])
    print(" ", edge["evidence"])
""")

markdown("""
## Capture a reviewer outcome

This is the portable review artifact. It references `decision_id`, rather than
copying personal or source values. In a real system, write each record to an
append-only case-management or audit store after authorisation.
""")

code("""
review_edge = next(edge for edge in result["matches"] if edge["decision"] == "review")

review_outcome = {
    "schema": "arche.review_outcome.v1",
    "decision_id": review_edge["decision_id"],
    "outcome": "different",
    "reviewer": "facility-steward-17",
    "reviewed_at": "2026-08-19T10:00:00Z",
    "reason": "The facilities share a generic name but are different sites.",
}

print(json.dumps(review_outcome, indent=2))
""")

markdown("""
The reviewer makes an identity claim: `same_entity`, `different`, or
`unresolved`. The review record does not change the original matcher output.
It supplies labels for a later evaluation.
""")

markdown("""
## Evaluate a completely labelled slice

This tiny slice has one confirmed same-entity pair and one confirmed different
pair. Complete labels make it possible to measure both recall and false
merges. A review queue by itself cannot measure missed matches.
""")

code("""
labelled_same_entity_pairs = {("facility-001", "osm-101")}
labelled_different_pairs = {("facility-002", "osm-102")}

report = evaluate(
    result["matches"],
    gold=labelled_same_entity_pairs,
    hard_negatives=labelled_different_pairs,
)

for key, value in report.items():
    print(f"{key}: {value}")
""")

markdown("""
## Make it a release gate

For a real population, save this report with the source-data version, sampling
plan, `result["pins"]`, thresholds, reviewer labels, and review-capacity limit.
Re-run it after changing any input or policy. Do not claim recall without a
complete true-pair mapping, and do not hide the review queue behind a single
precision number.

An agent can prepare records, explain evidence, and draft a review artifact.
It must not set the identity outcome or promote `review` to `match`.
""")

notebook = {
    "cells": [
        {
            "cell_type": kind,
            "id": f"cell-{index}",
            "metadata": {},
            "source": (source + "\n").splitlines(keepends=True),
            **({"execution_count": None, "outputs": []} if kind == CODE else {}),
        }
        for index, (kind, source) in enumerate(cells)
    ],
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

output = Path(__file__).resolve().parent / "12_review_feedback_and_evaluation.ipynb"
output.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {output} ({len(cells)} cells)")
