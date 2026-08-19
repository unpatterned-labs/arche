# SPDX-License-Identifier: Apache-2.0
"""Generate 11_places_and_products_tour.ipynb.

Run from the repository root:

    uv run --package arche-core python examples/notebooks/build_11.py
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
# arche in action: places and products

This is a short, reproducible tour of arche's record-resolution workflow.

It answers two practical questions:

1. When do two place records have enough evidence for an automatic match?
2. Can a product matcher find the same electronics item when retailers use
   different marketing titles?

The important output is not only `match`. `review` is a successful outcome
when the evidence does not justify an automatic merge.
""")

markdown("""
## Setup

Run this notebook from the repository root or any subdirectory within it. The
setup cell locates the checkout and imports the local package source.
""")

code("""
import csv
import sys
from pathlib import Path

REPO = Path.cwd().resolve()
while not (REPO / "packages" / "arche-core").exists() and REPO != REPO.parent:
    REPO = REPO.parent

if not (REPO / "packages" / "arche-core").exists():
    raise RuntimeError("Run this notebook from inside the arche repository.")

sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import crosswalk

print(f"repository: {REPO}")
""")

markdown("""
## Places: the same score can lead to different decisions

Both pairs below have identical names and are about 4.45 km apart. The
distinguishing factor is whether the shared name is rare enough to identify a
facility. `General Hospital` is common, so arche keeps it in review. `Gyaranya
Health Post` carries a distinctive signal, so it clears the automatic-match
gate.
""")

code("""
place_cases = [
    (
        "rare shared name",
        [{"id": "registry-1", "name": "Gyaranya Health Post", "lat": 12.00, "lon": 8.50}],
        [{"id": "survey-7", "name": "Gyaranya Health Post", "lat": 12.04, "lon": 8.50}],
    ),
    (
        "generic shared name",
        [{"id": "registry-2", "name": "General Hospital", "lat": 12.00, "lon": 8.50}],
        [{"id": "survey-8", "name": "General Hospital", "lat": 12.04, "lon": 8.50}],
    ),
    (
        "spelling variant",
        [{"id": "registry-3", "name": "Karfi Health Post", "lat": 11.60, "lon": 8.55}],
        [{"id": "survey-9", "name": "Karfi Primary Health Centre", "lat": 11.618, "lon": 8.55}],
    ),
]

for label, left, right in place_cases:
    edge = crosswalk(left, right, entity="place")["matches"][0]
    print(f"{label}: {edge['decision']}  score={edge['score']:.4f}  "
          f"distinctive={edge['distinctive_max']:.3f}")
    print(f"  evidence: {edge['evidence']}")
    print(f"  decision id: {edge['decision_id']}")
""")

markdown("""
`review` is not a failed match. It is a candidate that should be handled by a
defined review process. A pair below the review floor is not emitted at all,
which is different from declaring that the records are different entities.

The `decision_id` changes when the evidence or run configuration changes. Keep
it with any downstream action so the decision can be inspected later.
""")

markdown("""
## Products: a shared model code can outweigh different marketing copy

The electronics pack is experimental. It is designed for exact product-variant
matching, not product families, substitutes, bundles, or compatibility claims.
""")

code("""
electronics_left = [{
    "id": "retailer-a-1",
    "name": "Canon Deluxe Black Digital Camera Case 2595B002",
}]
electronics_right = [{
    "id": "retailer-b-1",
    "name": "Canon PSC-85 Soft Camera Case 2595B002",
}]

product_edge = crosswalk(
    electronics_left,
    electronics_right,
    entity="product_electronics",
    id_field="id",
)["matches"][0]

print(product_edge["decision"], f"score={product_edge['score']:.4f}")
print(product_edge["evidence"])
print(product_edge["decision_id"])
""")

markdown("""
The product titles disagree on most descriptive words. The shared code is a
stronger identity signal because it is rare in the product-code table. That is
why product matching needs a product-specific relation and evidence model,
rather than a generic text-similarity threshold.
""")

markdown("""
## Run the electronics pack on public labelled data

The vendored Leipzig Abt-Buy benchmark contains 1,081 Abt products, 1,092 Buy
products, and 1,097 known true pairs. Its mapping is complete, so false merges
can be measured rather than guessed.
""")

code("""
DATA = REPO / "data" / "er_bench" / "products"


def read_csv(name: str) -> list[dict[str, str]]:
    # The source files contain a few legacy byte sequences. Replacing only
    # undecodable bytes keeps the benchmark runnable and does not change IDs.
    with (DATA / name).open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle))


abt = read_csv("Abt.csv")
buy = read_csv("Buy.csv")
truth = {
    (row["idAbt"], row["idBuy"])
    for row in read_csv("abt_buy_perfectMapping.csv")
}

left = [{"id": row["id"], "name": row["name"]} for row in abt]
right = [{"id": row["id"], "name": row["name"]} for row in buy]

result = crosswalk(left, right, entity="product_electronics", id_field="id")
edges = {(edge["a_id"], edge["b_id"]): edge for edge in result["matches"]}
auto = {pair for pair, edge in edges.items() if edge["decision"] == "match"}
review = {pair for pair, edge in edges.items() if edge["decision"] == "review"}

true_positive = len(auto & truth)
false_positive = len(auto - truth)
precision = true_positive / len(auto)
recall = true_positive / len(truth)
f1 = 2 * precision * recall / (precision + recall)

print(f"records: Abt={len(left):,}, Buy={len(right):,}, true pairs={len(truth):,}")
print(f"candidate edges: {len(edges):,}")
print(f"automatic matches: {len(auto):,}, review candidates: {len(review):,}")
print(f"precision={precision:.4f}, recall={recall:.4f}, F1={f1:.4f}")
print(f"false merges={false_positive}")
""")

markdown("""
## Inspect a few correct matches

Metrics are useful, but collaborators should also inspect the underlying
records. This cell prints real matched titles from the benchmark and the
evidence used to link them.
""")

code("""
abt_names = {row["id"]: row["name"] for row in abt}
buy_names = {row["id"]: row["name"] for row in buy}

for abt_id, buy_id in sorted(auto & truth)[:3]:
    edge = edges[(abt_id, buy_id)]
    print(f"Abt: {abt_names[abt_id]}")
    print(f"Buy: {buy_names[buy_id]}")
    print(f"decision={edge['decision']}, score={edge['score']:.4f}")
    print(f"evidence={edge['evidence']}")
    print()
""")

markdown("""
## What this notebook establishes

- Place resolution can distinguish a rare shared facility name from a generic
  one, even when the raw score is the same.
- Product resolution can use a rare manufacturer code to link different retail
  titles.
- A `match` is a configured, evidence-backed action. It is not ground truth.
- Product matching remains limited to the experimental electronics lane. Add a
  labelled benchmark before extending the claim to other product categories.

For an agent integration, let the agent prepare records and explain the returned
evidence. Keep `review` as an escalation outcome, and never allow an agent to
silently upgrade it to `match`.
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

output = Path(__file__).resolve().parent / "11_places_and_products_tour.ipynb"
output.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {output} ({len(cells)} cells)")
