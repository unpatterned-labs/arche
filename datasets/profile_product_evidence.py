# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Profile structured product evidence against Nimble's shared ITEM_ID truth.

    uv run python datasets/profile_product_evidence.py <data-dir> --limit 400

This is not a matcher. It measures whether each field is present and agrees on
known cross-retailer pairs before it is made identity evidence in a product
profile.
"""

from __future__ import annotations

import argparse
import collections
import csv
import pathlib
import re
from typing import Any

from bench_product_matching import GM_COLUMNS, PER_KEY, _spread, find_feeds

csv.field_size_limit(10_000_000)

_FIELDS = ("brand", "model", "sku", "taxonomy")
_COLUMN = {
    "brand": "BRAND", "model": "MODEL", "sku": "SKU", "taxonomy": "TAXONOMY",
}
_NORMALISE = re.compile(r"[^a-z0-9]+")


def _normalise(value: str) -> str:
    """Normalise a structured string for an exact-agreement audit."""
    return _NORMALISE.sub("", value.casefold())


def _load(root: pathlib.Path, limit: int) -> list[tuple[dict[str, str], dict[str, str]]]:
    """Return a brand-spread sample of known Amazon-to-Walmart pairs."""
    by_item: dict[str, dict[str, dict[str, str]]] = collections.defaultdict(dict)
    for path in find_feeds(root, GM_COLUMNS):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                item = (row.get("ITEM_ID") or "").strip()
                company = (row.get("COMPANY_NAME") or "").strip()
                title = (row.get("PRODUCT_TITLE") or "").strip()
                if not (item and company and title):
                    continue
                by_item[item].setdefault(company, {
                    "item_id": item,
                    "title": title,
                    **{field: (row.get(column) or "").strip()
                       for field, column in _COLUMN.items()},
                })
    both = {item: sides for item, sides in by_item.items()
            if "Amazon" in sides and "Walmart" in sides}
    picked = _spread(
        both, PER_KEY,
        lambda sides: (sides["Amazon"]["brand"] or "?").upper(),
    )
    return [(both[item]["Amazon"], both[item]["Walmart"])
            for item in picked[:limit]]


def _field_report(
    pairs: list[tuple[dict[str, str], dict[str, str]]], field: str,
) -> dict[str, Any]:
    """Availability, true-pair agreement and false-pair exact collisions."""
    left_present = sum(bool(left[field]) for left, _ in pairs)
    right_present = sum(bool(right[field]) for _, right in pairs)
    comparable = [(left, right) for left, right in pairs
                  if left[field] and right[field]]
    agree = sum(_normalise(left[field]) == _normalise(right[field])
                for left, right in comparable)

    right_index: dict[str, list[str]] = collections.defaultdict(list)
    for _, right in pairs:
        if right[field]:
            right_index[_normalise(right[field])].append(right["item_id"])
    false_collisions = 0
    for left, right in pairs:
        if not left[field]:
            continue
        candidates = right_index[_normalise(left[field])]
        false_collisions += sum(candidate != right["item_id"] for candidate in candidates)
    distinct_right = len(right_index)
    commonest_right = max((len(ids) for ids in right_index.values()), default=0)
    return {
        "field": field,
        "left_present": left_present,
        "right_present": right_present,
        "comparable": len(comparable),
        "true_agree": agree,
        "agreement": agree / len(comparable) if comparable else 0.0,
        "false_collisions": false_collisions,
        "right_distinct": distinct_right,
        "right_commonest": commonest_right,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--limit", type=int, default=400)
    args = parser.parse_args()
    pairs = _load(pathlib.Path(args.data_dir), args.limit)
    if not pairs:
        print("no paired Amazon and Walmart records found")
        return 1
    print(f"sampled {len(pairs):,} known cross-retailer pairs")
    print("field       amazon  walmart  comparable  true agree  agreement  false collisions"
          "  walmart distinct  max frequency")
    print("-" * 114)
    for field in _FIELDS:
        row = _field_report(pairs, field)
        print(f"{row['field']:<11}{row['left_present']:>7}{row['right_present']:>9}"
              f"{row['comparable']:>12}{row['true_agree']:>12}"
              f"{row['agreement']:>11.1%}{row['false_collisions']:>18,}"
              f"{row['right_distinct']:>18,}{row['right_commonest']:>15,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
