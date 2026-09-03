# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Evaluate Arche pairwise resolution on OpenSanctions Pairs.

The benchmark is CC-BY-NC-4.0 evaluation data. Download it locally, outside
version control, from https://huggingface.co/datasets/sanctions-er-anon/opensanctions_pairs
and pass either ``sample_1000.json`` or the streaming ``pairs.json.gz`` file.
It is not a data pack and must not be included in a wheel or a production
runtime.

The current Arche packs answer person and organisation identity questions.
This script deliberately skips structural records (for example Occupancy and
Succession) and mixed-schema pairs instead of pretending their labels validate
a capability Arche does not implement yet.

Usage::

    uv run python data/scripts/benchmark_opensanctions_pairs.py \
        --input data/_cache/opensanctions_pairs/sample_1000.json
    uv run python data/scripts/benchmark_opensanctions_pairs.py \
        --input data/_cache/opensanctions_pairs/pairs.json.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

_ORGANISATION_SCHEMAS = frozenset({"Company", "LegalEntity", "Organization"})


def iter_pairs(path: Path) -> Iterator[dict[str, Any]]:
    """Yield labelled pairs from the published sample or full JSONL archive."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line.strip():
                    yield _pair(json.loads(line), path, line_number)
        return

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    pairs = payload.get("pairs") if isinstance(payload, Mapping) else payload
    if not isinstance(pairs, list):
        raise ValueError(f"{path} must contain a 'pairs' list")
    for line_number, pair in enumerate(pairs, start=1):
        yield _pair(pair, path, line_number)


def evaluate_pairs(pairs: Iterator[dict[str, Any]]) -> dict[str, object]:
    """Evaluate supported pairs and return counts without retaining raw values."""
    from arche.resolve import compare

    labels: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    true_positive = false_positive = surfaced_positive = 0

    for pair in pairs:
        entity = _entity_for_pair(pair)
        if entity is None:
            skipped[_schema_key(pair)] += 1
            continue
        judgement = pair["judgement"]
        labels[judgement] += 1
        receipt = compare(
            _record_for_pair_side(pair["left"], entity),
            _record_for_pair_side(pair["right"], entity),
            entity=entity,
        )
        decisions[receipt.identity] += 1
        if judgement == "positive" and receipt.identity in {"same_entity", "review"}:
            surfaced_positive += 1
        if receipt.identity == "same_entity":
            if judgement == "positive":
                true_positive += 1
            else:
                false_positive += 1

    positives = labels["positive"]
    auto_matches = true_positive + false_positive
    return {
        "evaluated_pairs": sum(labels.values()),
        "labels": dict(sorted(labels.items())),
        "decisions": dict(sorted(decisions.items())),
        "skipped_schema_pairs": dict(sorted(skipped.items())),
        "auto_link": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "precision": _ratio(true_positive, auto_matches),
            "recall": _ratio(true_positive, positives),
            "surfaced_recall": _ratio(surfaced_positive, positives),
        },
        "review_count": decisions["review"],
    }


def _pair(value: object, path: Path, line_number: int) -> dict[str, Any]:
    """Validate one input pair enough to fail with an actionable location."""
    if not isinstance(value, dict):
        raise ValueError(f"{path}:{line_number} must be a JSON object")
    required = {"left", "right", "judgement"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"{path}:{line_number} is missing {sorted(missing)!r}")
    if value["judgement"] not in {"positive", "negative"}:
        raise ValueError(f"{path}:{line_number} has an unknown judgement")
    if not isinstance(value["left"], dict) or not isinstance(value["right"], dict):
        raise ValueError(f"{path}:{line_number} needs object-valued left and right records")
    return value


def _entity_for_pair(pair: Mapping[str, object]) -> str | None:
    """Map supported OpenSanctions schema pairs to current Arche packs."""
    left_schema = pair["left"].get("schema")
    right_schema = pair["right"].get("schema")
    if left_schema == right_schema == "Person":
        return "person"
    if left_schema in _ORGANISATION_SCHEMAS and right_schema in _ORGANISATION_SCHEMAS:
        return "organisation"
    return None


def _schema_key(pair: Mapping[str, object]) -> str:
    """Return a PII-free schema pair label for skipped records."""
    return f"{pair['left'].get('schema', 'unknown')}->{pair['right'].get('schema', 'unknown')}"


def _record_for_pair_side(record: Mapping[str, object], entity: str) -> dict[str, str]:
    """Map public benchmark fields into one current resolver record."""
    properties = record.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}
    result = {"id": str(record.get("id", "")), "name": str(record.get("caption", ""))}
    _copy_first(properties, result, "address", "address")
    if entity == "person":
        _copy_first(properties, result, "birthDate", "birth_date")
        _copy_first(properties, result, "passportNumber", "national_id")
        _copy_first(properties, result, "idNumber", "national_id")
        _copy_first(properties, result, "email", "email")
    else:
        _copy_first(properties, result, "registrationNumber", "registration_id")
    return result


def _copy_first(
    properties: Mapping[str, object],
    target: dict[str, str],
    source: str,
    destination: str,
) -> None:
    """Copy the first non-empty list value when the target has no value yet."""
    if destination in target:
        return
    values = properties.get(source)
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value:
                target[destination] = value
                return


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a ratio only when the benchmark contains its denominator."""
    return numerator / denominator if denominator else None


def main() -> int:
    """Run a local OpenSanctions Pairs evaluation and print JSON metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="local sample JSON or full JSONL gzip",
    )
    parser.add_argument("--output", type=Path, help="optional local JSON result path")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"benchmark input does not exist: {args.input}")

    result = evaluate_pairs(iter_pairs(args.input))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
