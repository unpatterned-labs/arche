# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the local OpenSanctions Pairs evaluator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _benchmark_module():
    """Load the standalone benchmark script without making data a package."""
    script = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "scripts"
        / "benchmark_opensanctions_pairs.py"
    )
    spec = importlib.util.spec_from_file_location(
        "benchmark_opensanctions_pairs", script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_opensanctions_evaluator_reports_supported_and_skipped_schema_pairs(tmp_path):
    """It measures person/organisation pairs without claiming structural support."""
    sample = {
        "pairs": [
            {
                "left": {
                    "id": "person-a",
                    "schema": "Person",
                    "caption": "Ada Lovelace",
                    "properties": {"birthDate": ["1815-12-10"]},
                },
                "right": {
                    "id": "person-b",
                    "schema": "Person",
                    "caption": "Ada Lovelace",
                    "properties": {"birthDate": ["1815-12-10"]},
                },
                "judgement": "positive",
            },
            {
                "left": {
                    "id": "occupancy-a",
                    "schema": "Occupancy",
                    "caption": "Occupancy",
                    "properties": {},
                },
                "right": {
                    "id": "occupancy-b",
                    "schema": "Occupancy",
                    "caption": "Occupancy",
                    "properties": {},
                },
                "judgement": "positive",
            },
        ]
    }
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(sample), encoding="utf-8")

    module = _benchmark_module()
    result = module.evaluate_pairs(module.iter_pairs(path))

    assert result["evaluated_pairs"] == 1
    assert result["labels"] == {"positive": 1}
    assert result["skipped_schema_pairs"] == {"Occupancy->Occupancy": 1}
    assert result["auto_link"]["false_positive"] == 0
