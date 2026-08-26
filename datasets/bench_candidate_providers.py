# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Compare candidate retrieval routes before product-linkage scoring.

Run against the local Nimble export whose ITEM_ID spans Amazon and Walmart:

    uv run python datasets/bench_candidate_providers.py <data-dir> --limit 400

The truth is complete over the sampled block. This measures the retrieval
ceiling separately from the matcher: a true pair omitted by a candidate
provider cannot be recovered by a better threshold or comparator.
"""

from __future__ import annotations

import argparse
import collections
import math
import pathlib
import re
import sys
import time
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages" / "arche-core" / "src"))

from arche.resolve import ENTITY_PACKS, TokenFrequencyTable, reconcile  # noqa: E402
from bench_product_matching import load_general_merchandise  # noqa: E402

_TOKEN = re.compile(r"[a-z0-9]+")
_MAX_POSTING_SHARE = 0.1


def _tokens(value: str) -> frozenset[str]:
    """Stable, intentionally simple title tokens for candidate retrieval."""
    return frozenset(token for token in _TOKEN.findall(value.casefold())
                     if len(token) > 1)


def _normalised_title(value: str) -> str:
    """Normalise punctuation and casing without changing title word order."""
    return " ".join(token for token in _TOKEN.findall(value.casefold())
                    if len(token) > 1)


def _exact_title_candidates(
    a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retrieve only punctuation- and case-normalised title agreements."""
    by_title: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for record in b_rows:
        title = _normalised_title(record["name"])
        if title:
            by_title[title].append(record)
    return [
        {"a_id": a["id"], "b_id": b["id"], "route": "exact-title.v1",
         "retrieval_score": 1.0}
        for a in a_rows
        for b in by_title[_normalised_title(a["name"])]
        if _normalised_title(a["name"])
    ]


def _idf_token_candidates(
    a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]], top_k: int,
) -> list[dict[str, Any]]:
    """Retrieve up to ``top_k`` target titles by rare-token weighted overlap."""
    b_tokens = [_tokens(record["name"]) for record in b_rows]
    postings: dict[str, list[int]] = collections.defaultdict(list)
    for index, tokens in enumerate(b_tokens):
        for token in tokens:
            postings[token].append(index)
    maximum_posting = max(1, int(len(b_rows) * _MAX_POSTING_SHARE))
    weights = {
        token: math.log((len(b_rows) + 1) / (len(indices) + 1)) + 1.0
        for token, indices in postings.items()
        if len(indices) <= maximum_posting
    }

    candidates: list[dict[str, Any]] = []
    for a in a_rows:
        a_tokens = _tokens(a["name"])
        candidate_indices = {
            index for token in a_tokens if token in weights
            for index in postings[token]
        }
        scored: list[tuple[float, int]] = []
        for index in candidate_indices:
            b_set = b_tokens[index]
            shared = a_tokens & b_set
            numerator = sum(weights[token] for token in shared if token in weights)
            denominator = sum(weights[token] for token in a_tokens | b_set
                              if token in weights)
            if denominator:
                scored.append((numerator / denominator, index))
        for score, index in sorted(scored, key=lambda item: (-item[0], item[1]))[:top_k]:
            candidates.append({
                "a_id": a["id"], "b_id": b_rows[index]["id"],
                "route": "idf-token-jaccard.v1", "retrieval_score": score,
            })
    return candidates


def _measure(
    name: str,
    a_rows: list[dict[str, Any]],
    b_rows: list[dict[str, Any]],
    truth: dict[str, str],
    candidate_pairs: list[dict[str, Any]] | None = None,
    candidate_pins: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one provider through Arche and report retrieval plus decision metrics."""
    tf = TokenFrequencyTable.from_corpus(
        [record["name"] for record in a_rows] +
        [record["name"] for record in b_rows]
    )
    started = time.perf_counter()
    result = reconcile(
        a_rows, b_rows, ENTITY_PACKS["product_home_goods"], tf=tf,
        id_field="id", threshold=0.7,
        truth_pairs=list(truth.items()),
        candidate_pairs=candidate_pairs,
        candidate_pins=candidate_pins,
    )
    seconds = time.perf_counter() - started
    automatic = [edge for edge in result["matches"] if edge["decision"] == "match"]
    true_automatic = sum(
        truth.get(edge["a_id"]) == edge["b_id"] for edge in automatic
    )
    false_merges = len(automatic) - true_automatic
    held = sum(
        truth.get(edge["a_id"]) == edge["b_id"] and edge["decision"] == "review"
        for edge in result["matches"]
    )
    precision = true_automatic / len(automatic) if automatic else 0.0
    recall = true_automatic / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "provider": name,
        "candidate_pairs": result["blocking"]["candidate_pairs"],
        "candidate_recall": result["blocking"].get("recall", 0.0),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_merges": false_merges,
        "true_review": held,
        "seconds": seconds,
    }


def _print(rows: list[dict[str, Any]]) -> None:
    print("\nprovider                 candidates  cand recall    precision   recall      F1"
          "  false  review    sec")
    print("-" * 100)
    for row in rows:
        print(f"{row['provider']:<24}{row['candidate_pairs']:>10,}"
              f"{row['candidate_recall']:>13.1%}{row['precision']:>13.3f}"
              f"{row['recall']:>9.3f}{row['f1']:>9.3f}{row['false_merges']:>7}"
              f"{row['true_review']:>8}{row['seconds']:>7.1f}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--top-k", type=int, nargs="+", default=[20])
    args = parser.parse_args()

    a_rows, b_rows, truth = load_general_merchandise(
        pathlib.Path(args.data_dir), args.limit
    )
    if not truth:
        return 1
    exact = _exact_title_candidates(a_rows, b_rows)
    rows = [
        _measure("arche-union", a_rows, b_rows, truth),
        _measure(
            "exact-title", a_rows, b_rows, truth, exact,
            {"provider": "exact-title.v1", "normaliser": "tokens.v1",
             "top_k": None},
        ),
    ]
    for top_k in args.top_k:
        token = _idf_token_candidates(a_rows, b_rows, top_k)
        rows.append(_measure(
            f"idf-token-top-{top_k}", a_rows, b_rows, truth, token,
            {"provider": "idf-token-jaccard.v1", "normaliser": "tokens.v1",
             "max_posting_share": _MAX_POSTING_SHARE, "top_k": top_k},
        ))
    _print(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
