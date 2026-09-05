# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Build the bounded local-PDF person-resolution notebook.

    uv run python examples/notebooks/build_24_person_document_resolution_case.py
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
# Resolve a local PDF corpus to people, cautiously

**Question:** Across the PDFs in `data/docs`, which documents have enough independent identity evidence to be proposed as the same person, which look different, and which need more evidence?

This notebook runs entirely locally. It never writes source text, names, emails, addresses, phone numbers, or PDF paths to its output artifact. A `same_entity` result is a resolver proposal, not a merge; `review` opens a bounded `ResolutionCase`; `different` is only the result of the available evidence, not proof that two real people differ.
""")

md("""
## 1. Why this extraction route

The normal `arche.resolve_documents(...)` route uses Docling. On this machine Docling/model-assisted extraction can exceed the notebook's practical memory budget for this corpus. The primary path below therefore uses a caller-owned, local `pypdf` text adapter, then returns immediately to Arche for jurisdiction inference, statute-aware detection, matching, uncertainty, cases, and planning. No regular expressions or model guesses are added in the notebook.

Set `USE_DOCLING_SAMPLE=True` only when you want to try the normal Arche parser on one selected PDF and have enough memory for it. The complete corpus run remains bounded and CPU-first.
""")

code("""
from __future__ import annotations

import hashlib
import json
import warnings
from itertools import combinations
from pathlib import Path

import arche
from pypdf import PdfReader


def repository_root() -> Path:
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "data" / "docs").is_dir():
            return candidate
    raise RuntimeError("Run this notebook from the Arche repository or a child directory.")


ROOT = repository_root()
PDFS = sorted((ROOT / "data" / "docs").glob("*.pdf"))
DOC_IDS = {path: f"doc-{index:02d}" for index, path in enumerate(PDFS, start=1)}
assert PDFS, "No PDFs found under data/docs."
print({"pdf_count": len(PDFS), "document_ids": list(DOC_IDS.values())})
""")

code("""
# This inventory contains no paths, document text, or extracted values.
inventory = []
for path in PDFS:
    reader = PdfReader(path)
    inventory.append(
        {
            "document_id": DOC_IDS[path],
            "pages": len(reader.pages),
            "bytes": path.stat().st_size,
            "encrypted": bool(reader.is_encrypted),
            "artifact_sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
print(inventory)
""")

code("""
# Optional normal Arche parser smoke test. Keep disabled for a bounded corpus run.
USE_DOCLING_SAMPLE = False
if USE_DOCLING_SAMPLE:
    from arche.doc import parse

    parsed = parse(str(PDFS[0]))
    print(
        {
            "document_id": DOC_IDS[PDFS[0]],
            "text_length": len(parsed.text),
            "parser": parsed.provenance.get("parser"),
            "parser_version": parsed.provenance.get("parser_version"),
            "ocr": parsed.provenance.get("ocr"),
        }
    )
else:
    print("Docling sample disabled; using local pypdf text with Arche detection.")
""")

md("""
## 2. Extract only detector-backed identity attributes

`Pipeline` is the evidence layer: it applies the jurisdiction proposal and its conservative baseline when no statute pack covers the document. The adapter retains only the first detector-backed value for each identity field in memory. It does not print the values.
""")

code("""
from arche import Pipeline, resolve
from arche.jurisdictions.infer import infer_jurisdiction

DETECTION_FIELDS = {
    "EMAIL": "email",
    "PHONE": "phone",
    "NIN": "national_id",
    "BVN": "national_id",
    "NATIONAL_ID": "national_id",
    "PASSPORT": "passport",
    "ADDRESS": "address",
}


def local_pdf_text(path: Path) -> str:
    # Caller-owned text adapter; values stay in this notebook process.
    return "\\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def detector_record(path: Path) -> tuple[dict[str, str], dict[str, object]]:
    text = local_pdf_text(path)
    if not text.strip():
        raise ValueError("no extractable local PDF text")
    jurisdiction = infer_jurisdiction(text).country
    kwargs = {"on_uncovered": "baseline"} if jurisdiction else {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        detections = Pipeline(jurisdiction=jurisdiction, **kwargs).process(text).detections
    record: dict[str, str] = {}
    census: dict[str, int] = {}
    for detection in detections:
        category = str(detection.category)
        census[category] = census.get(category, 0) + 1
        field = DETECTION_FIELDS.get(category.rsplit("-", 1)[-1].upper())
        value = str(detection.text or "")
        if field and value and field not in record:
            record[field] = value
    return record, {"jurisdiction": jurisdiction, "detections": census, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
""")

code("""
records: dict[str, dict[str, str]] = {}
document_provenance: dict[str, dict[str, object]] = {}
errors: dict[str, str] = {}
for path in PDFS:
    document_id = DOC_IDS[path]
    try:
        record, provenance = detector_record(path)
    except Exception as error:
        errors[document_id] = type(error).__name__
        continue
    if not record:
        errors[document_id] = "no_detector_backed_identity_attributes"
        continue
    records[document_id] = record
    document_provenance[document_id] = provenance

print(
    {
        "records_with_identity_attributes": len(records),
        "field_names_by_document": {key: sorted(value) for key, value in records.items()},
        "skipped": errors,
    }
)
""")

md("""
## 3. Compare every surfaced document pair

This calls Arche's person resolver. The output is intentionally limited to aliases, outcome, score, factor names, and decision ID; the original values never leave the notebook process.
""")

code("""
decisions = []
for left, right in combinations(sorted(records), 2):
    decision = resolve.compare(records[left], records[right], entity="person")
    decisions.append(
        {
            "left": left,
            "right": right,
            "identity": decision.identity,
            "score": round(float(decision.score), 4),
            "factor_names": sorted(decision.factors),
            "decision_id": decision.decision_id,
        }
    )

outcomes = {
    outcome: sum(item["identity"] == outcome for item in decisions)
    for outcome in sorted({item["identity"] for item in decisions})
}
print({"pairs_compared": len(decisions), "outcomes": outcomes})
print(decisions)
""")

md("""
## 4. Candidate groups are not automatic entities

Only direct `same_entity` proposals form a displayed candidate group. A `review` edge is never treated as transitive evidence, and no group is written as an Arche entity. That prevents “A might be B; B might be C; therefore A is C” from silently becoming a person merge.
""")

code("""
parent = {document_id: document_id for document_id in records}


def find(document_id: str) -> str:
    while parent[document_id] != document_id:
        parent[document_id] = parent[parent[document_id]]
        document_id = parent[document_id]
    return document_id


def union(left: str, right: str) -> None:
    left_root, right_root = find(left), find(right)
    if left_root != right_root:
        parent[right_root] = left_root


for item in decisions:
    if item["identity"] == "same_entity":
        union(item["left"], item["right"])

groups: dict[str, list[str]] = {}
for document_id in records:
    groups.setdefault(find(document_id), []).append(document_id)
candidate_groups = [sorted(group) for group in groups.values() if len(group) > 1]
review_pairs = [item for item in decisions if item["identity"] == "review"]
print({"candidate_same_person_groups": candidate_groups, "review_pairs": len(review_pairs)})
""")

md("""
## 5. Make uncertainty durable and plan only permitted evidence work

Every ambiguous pair becomes a vNext `ResolutionCase` with hash-only document Observations and one bounded `registry_lookup` action. The deterministic planner can recommend that action because it is explicitly permitted and within budget. It does not execute a connector, create a person, or release a decision.
""")

code("""
from datetime import UTC, datetime

from arche.runtime import (
    EvidenceAction,
    EvidenceGap,
    Observation,
    ResolutionBudget,
    ResolutionCase,
    ResolutionIntent,
    ToolCapability,
    attach,
    new_evidence_action_id,
    new_resolution_case_id,
)

engine = attach("duckdb:///:memory:")
now = datetime.now(UTC)
observations = []
for path in PDFS:
    document_id = DOC_IDS[path]
    observations.append(
        Observation(
            observation_id=f"obs_{document_id}",
            source_id="caller-owned-pdf",
            source_record_id=None,
            recorded_at=now,
            content_hash="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            provenance={"kind": "local_pdf", "document_id": document_id},
        )
    )
engine.store.write_observations(observations)

cases, actions = [], []
for pair in review_pairs:
    case = ResolutionCase(
        case_id=new_resolution_case_id(),
        question=f"Do {pair['left']} and {pair['right']} describe the same person?",
        observation_ids=(f"obs_{pair['left']}", f"obs_{pair['right']}"),
        candidate_entity_ids=(),
        opened_at=now,
        uncertainty={"resolver_outcome": "review", "decision_id": pair["decision_id"]},
        evidence_gaps=(
            EvidenceGap(
                field="independent_identifier",
                reason="detector-backed document attributes were not sufficient to link safely",
                priority=0,
                permitted_action_types=("registry_lookup",),
            ),
        ),
        intent=ResolutionIntent(
            entity_type="person",
            operation="reconcile",
            available_fields=tuple(sorted(set(records[pair["left"]]) | set(records[pair["right"]]))),
            policy_pin="document-person-v1",
            candidate_pairs=1,
        ),
    )
    action = EvidenceAction(
        action_id=new_evidence_action_id(),
        case_id=case.case_id,
        action_type="registry_lookup",
        source_id="external_person_registry",
        permitted_at=now,
        policy_pin="document-person-v1",
        max_cost=1.0,
    )
    cases.append(case)
    actions.append(action)

engine.store.write_resolution_cases(cases)
engine.store.write_evidence_actions(actions)
capability = ToolCapability(
    "external_person_registry", ("registry_lookup",), "document-person-v1"
)
plans = []
for case in cases:
    plan = engine.plan_case(
        case.case_id,
        capabilities=(capability,),
        budget=ResolutionBudget(max_actions=1, max_cost=1.0),
    )
    engine.record_case_plan(plan, recorded_at=now)
    plans.append(plan)
print({"review_cases": len(cases), "planned_actions": sum(len(plan.actions) for plan in plans)})
""")

md("""
## 6. Export a value-free inspection artifact

The output is suitable for comparison across runs: aliases, hashes, field names, outcome labels, decision IDs, and case counts only. It is not truth data and it is not an entity ledger update.
""")

code("""
artifact = {
    "schema": "arche.document_person_resolution.v1",
    "documents": [
        {
            "document_id": row["document_id"],
            "pages": row["pages"],
            "artifact_sha256": row["artifact_sha256"],
            "field_names": sorted(records.get(row["document_id"], {})),
            "jurisdiction": document_provenance.get(row["document_id"], {}).get("jurisdiction"),
        }
        for row in inventory
    ],
    "decisions": decisions,
    "candidate_same_person_groups": candidate_groups,
    "review_case_count": len(cases),
    "skipped": errors,
}
OUTPUT = ROOT / "outputs" / "document_person_resolution" / "masked-results.json"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
print({"artifact": str(OUTPUT.relative_to(ROOT)), "bytes": OUTPUT.stat().st_size})
""")

md("""
## 7. Read the result correctly

- `same_entity`: a candidate result from the configured resolver, not an automatic person merge.
- `review`: the right place for agentic evidence acquisition. A caller may use the persisted action with a policy-pinned registry connector, then convert reviewed results into Evidence before policy can act.
- `different`: the available extracted attributes favour a distinction; it is not proof that two real-world people differ.

To make a performance or accuracy claim, add labeled ground truth and an evaluated benchmark bundle. This notebook is a controlled operational smoke test over caller-owned documents, not a benchmark.
""")

notebook = {
    "cells": [
        {
            "id": f"person-corpus-{index:02d}",
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

output = Path(__file__).with_name("24_person_document_resolution_case.ipynb")
output.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
print(f"wrote {output.name}: {len(cells)} cells")
