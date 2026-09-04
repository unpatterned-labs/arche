# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build the five-minute tea resolution walkthrough notebook.

    uv run python examples/notebooks/build_23_agentic_tea_resolution_case.py
"""

from __future__ import annotations

import json
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def md(text: str) -> None:
    """Append a Markdown cell."""
    cells.append((MD, text.strip("\n")))


def code(text: str) -> None:
    """Append a code cell."""
    cells.append((CODE, text.strip("\n")))


md("""
# Resolve a tea supplier in five minutes

**Start with a useful answer. Escalate only when the evidence is weak.**

This walkthrough uses one fictional but fully local shipment document. It deliberately does **not** claim anything about Unilever or a real supply chain. Replace the document and candidate export with records you control. Arche returns proposed fields and candidates; when no candidate is safe to link, it opens a case and explains the next evidence worth collecting.
""")

md("""
## 1. First value: resolve one document against a supplier master

This is the normal happy path. Arche reads local text directly; PDFs, scans, and images use the optional Docling/OCR path. The five lines below extract labelled supplier, distributor, estate, registration, and country fields, then compare the supplier against a caller-owned candidate record.
""")

code("""
from pathlib import Path

from arche import resolve_documents

registry = [{"entity_id": "ent_kijani", "name": "Kijani Tea Exporters Limited", "country": "Kenya"}]
shipment = Path("tea_supplier_shipment.txt")
if not shipment.is_file():
    shipment = Path("examples/notebooks/tea_supplier_shipment.txt")
report = resolve_documents(
    shipment, candidates=registry,
    entity="organisation", extraction_backend="regex", progress=False,
)
print(report.review(reveal=True))
""")

md("""
The result is not a silent merge. The candidate decision is a **proposal**; `review()` identifies the extracted field spans and masks values unless you explicitly request them. A reviewer or application must turn reviewed fields into vNext Evidence before a receipt, policy action, or entity-memory change is possible.
""")

md("""
## 2. When there is no safe candidate

Different names should not be forced together just because they both handle tea. Here the same document is compared with a different candidate. Arche opens an unresolved `ResolutionCase`, rather than creating a guessed link or treating absence as proof that the organisations are different.
""")

code("""
unresolved = resolve_documents(
    shipment,
    candidates=[{"entity_id": "ent_kericho", "name": "Kericho Highlands Processing", "country": "Kenya"}],
    entity="organisation", extraction_backend="regex", progress=False,
)
print(unresolved.review(reveal=True)["cases"][0])
""")

md("""
## 3. Let the case planner say what would change the answer

The front door has already identified the document observation, the candidate, the missing independent registration evidence, and permitted actions. Persist that value-free state in a caller-owned runtime only when you want to plan or execute follow-up work.
""")

code("""
import arche
from arche.runtime import ResolutionBudget, ToolCapability

engine = arche.attach("duckdb:///:memory:")
saved = unresolved.persist(engine)
case_id = saved["case_ids"][0]
plan = engine.plan_case(
    case_id,
    capabilities=(
        ToolCapability("external_registry", ("registry_lookup",), "document-resolution-v1"),
        ToolCapability("caller_document", ("document_extract",), "document-resolution-v1"),
    ),
    budget=ResolutionBudget(1, 1.0),
)
print(plan.actions[0].rationale)
""")

md("""
That rationale is the planner's inspectable reasoning: **which uncertainty exists, which action is permitted, and why it is worth its cost.** There is no hidden automatic lookup and no invented relationship.
""")

md("""
## 4. Real PDF, scan, or image input

For a document you own, the matching CLI front door emits the same masked review artifact. Add `--store` only when you want to persist its value-free case, Observation, and permitted actions in a local runtime. A persisted `registry_lookup` action can use a caller-owned, policy-pinned HTTPS connector; its query remains transient and its response becomes an Observation.
""")

code("""
# arche resolve-documents tea-shipment.pdf --entity organisation --candidates suppliers.json --store tea.duckdb --out tea-review.json
#
# If the review artifact opens a case and you want to acquire registry evidence:
# arche case registry-lookup CASE_ID REGISTRY_ACTION_ID --connector registry.json --store tea.duckdb
#
# Or, to extract a caller-owned PDF/image through a separately planned local action:
# arche case open tea-shipment.pdf --store tea.duckdb
# arche case plan CASE_ID --enable-local-document
# arche case ingest CASE_ID ACTION_ID tea-shipment.pdf --approved-by analyst-1
# arche case evidence CASE_ID ACTION_ID reviewed-fields.json --review-id review-1
# arche case propose-tea CASE_ID ACTION_ID reviewed-fields.json --review-id review-1 --supplier-entity ent_supplier
# arche case review CASE_ID --out tea-review.json --html tea-review.html
""")

md("""
`reviewed-fields.json` is caller-owned and can contain fields such as `supplier_name`, `distributor_name`, `registration_id`, `span`, and `page`. Reviewers see the original document in their application; Arche stores the durable evidence references needed to later explain or revise the decision.
""")

md("""
## 5. What agents may do next

An optional agent receives the same case assessment and can recommend only already-permitted actions or already-qualified resolver methods. Good recommendations are concrete: “obtain the Kenyan registration identifier,” “compare the distributor's shipment reference,” or “send these two fields to review.” It must not turn an absent match into a positive link.

Splink, RecordLinkage, and domain matchers belong after this basic experience. Arche should select them only when their exact configuration has a completed compatible benchmark qualification. A notebook must never manufacture a qualification from a review pack or a placeholder hash.
""")

md("""
## 6. Roadmap from here

1. **Review interaction bridge:** connect a caller-owned review client to reviewed fields, selected semantic mappings, and acceptance requests through the existing case APIs. The source document remains client-side.
2. **Resolver selection:** qualify deterministic, Splink, and domain configurations on complete mappings, then let the planner select only eligible methods under a budget.
3. **Entity memory:** promote accepted, independently supported supplier/distributor/estate claims and relationships; preserve contradictions and open questions for the next shipment.
""")

nb = {
    "cells": [
        {
            "id": f"tea-{index:02d}",
            "cell_type": cell_type,
            "metadata": {},
            "source": (source + "\n").splitlines(True),
            **({"execution_count": None, "outputs": []} if cell_type == CODE else {}),
        }
        for index, (cell_type, source) in enumerate(cells, start=1)
    ],
    "metadata": {
        "kernelspec": {"display_name": "Arche venv", "language": "python", "name": "arche-venv"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

out = Path(__file__).with_name("23_agentic_tea_resolution_case.ipynb")
out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {out.name}: {len(cells)} cells")
