# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The detection benchmark's scoring, on a slice of the constructed set.

Not the benchmark itself -- that runs from `data/scripts/benchmark_pii.py` and
publishes to the benchmarks page. This guards the harness: that the set loads,
that a hit is an overlap of the same category, that a detection over nothing
is a false positive and one over another category is nested, and that the
report has the fields the docs quote.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "data" / "scripts" / "benchmark_pii.py"
SET = REPO / "data" / "pii_bench" / "african_context_v0.jsonl"


@pytest.fixture(scope="module")
def harness():
    if not SCRIPT.exists() or not SET.exists():
        pytest.skip("benchmark harness or set not present in this checkout")
    spec = importlib.util.spec_from_file_location("benchmark_pii", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rows():
    lines = SET.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[:12] if line.strip()]


def test_the_set_is_well_formed(rows):
    for row in rows:
        for span in row["spans"] + row["negatives"]:
            assert row["text"][span["start"]:span["end"]], (row["id"], span)
        assert row["jurisdiction"] in {"NG", "KE", "ZA", "GH"}


def test_basic_scores_the_validated_categories_perfectly(harness, rows):
    report = harness.run(rows, "basic")
    assert report["backend"] == "basic" and report["model"] is None
    cats = report["categories"]
    assert cats["PII-3-EMAIL"]["recall"] == 1.0
    assert cats["PII-2-NIN"]["recall"] == 1.0
    # No detector for these in the base install: the recall says so, at zero.
    assert cats["PII-8-PASSWORD"]["recall"] == 0.0
    assert set(report["names_by_pool"]) <= {"lexicon", "heldout"}


def test_a_detection_over_nothing_is_a_false_positive(harness):
    row = {"id": "x", "jurisdiction": "NG",
           "text": "Invoice ORD-97880932 for Adesola Okonkwo.",
           "spans": [{"start": 25, "end": 40, "category": "PII-1-NAME", "pool": "lexicon"}],
           "negatives": [{"start": 8, "end": 20, "kind": "order_no"}]}
    report = harness.run([row], "basic")
    assert report["categories"]["PII-1-NAME"]["hit"] == 1
    landed = report["false_positives_landed_on"]
    assert set(landed) <= {"order_no", "free text"}
    assert report["false_positives"] == sum(landed.values())


def test_a_detection_inside_another_category_is_nested_not_false(harness):
    row = {"id": "y", "jurisdiction": "NG",
           "text": "Deliver to 12 Zaria Road, Kano.",
           "spans": [{"start": 11, "end": 30, "category": "PII-4-ADDRESS"}],
           "negatives": []}
    report = harness.run([row], "basic")
    assert report["false_positives"] == 0
    assert report["nested"] >= 1        # the LOCATION "Kano" inside the ADDRESS
