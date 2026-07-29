# Copyright 2026 unpatterned.org
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reconciliation metrics — measure the matcher against labelled pairs.

Given :func:`arche.resolve.reconcile`'s output and a set of gold (a_id, b_id)
true-match pairs, compute the numbers that decide whether a matcher is safe to
run a master facility list on:

* **precision / recall / F1** on the ``match`` decisions;
* **false-merge rate** — the fraction of hard-negative pairs (genuinely
  different things, e.g. a clinic and a mosque at one coordinate) that were
  auto-``match``ed. This is the SAFETY metric; a bad merge misroutes real-world
  resources. Target 0.
* **surfaced recall** — gold pairs that reached a human's attention (``match``
  *or* ``review``); the honest measure when the engine routes conservatively.
* **review-queue size** — the real human cost.

Pure Python, no dependencies. Feed it labelled slices (transliteration,
type-variant, near-duplicate negative, GPS-discordant positive) to get the
per-slice breakdown a partner like GRID3 will ask for.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _pairs(items: Iterable) -> set[tuple]:
    return {tuple(p) for p in items}


def evaluate(
    matches: list[dict[str, Any]],
    gold: Iterable,
    *,
    hard_negatives: Iterable = (),
) -> dict[str, Any]:
    """Score reconcile output against gold pairs.

    Parameters
    ----------
    matches:
        The ``matches`` list from :func:`reconcile` — dicts carrying ``a_id``,
        ``b_id`` and ``decision`` (``"match"`` / ``"review"``).
    gold:
        Iterable of ``(a_id, b_id)`` pairs that are true matches.
    hard_negatives:
        Iterable of ``(a_id, b_id)`` pairs that must NOT be auto-matched
        (near-duplicate negatives). Drives ``false_merge_rate``.

    Returns
    -------
    dict
        precision / recall / f1 / true_positives / false_positives /
        false_negatives / matches / review_queue / surfaced_recall /
        false_merge_rate / false_merges.
    """
    gold_set = _pairs(gold)
    neg_set = _pairs(hard_negatives)

    matched = {(m["a_id"], m["b_id"]) for m in matches if m.get("decision") == "match"}
    surfaced = {
        (m["a_id"], m["b_id"]) for m in matches
        if m.get("decision") in ("match", "review")
    }
    review = sum(1 for m in matches if m.get("decision") == "review")

    tp = len(matched & gold_set)
    fp = len(matched - gold_set)
    fn = len(gold_set - matched)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    false_merges = matched & neg_set
    fmr = len(false_merges) / len(neg_set) if neg_set else 0.0
    surfaced_recall = len(surfaced & gold_set) / len(gold_set) if gold_set else 1.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "matches": len(matched),
        "review_queue": review,
        "surfaced_recall": round(surfaced_recall, 4),
        "false_merge_rate": round(fmr, 4),
        "false_merges": sorted(false_merges),
    }


def evaluate_slices(
    matches: list[dict[str, Any]],
    slices: dict[str, dict[str, Iterable]],
) -> dict[str, dict[str, Any]]:
    """Per-slice metrics. ``slices`` maps a slice name to ``{"gold": ..., "hard_negatives": ...}``.

    Lets a benchmark report where the matcher wins and loses (transliteration,
    type-variant, near-duplicate negative, ...), not just an average.
    """
    return {
        name: evaluate(
            matches, spec.get("gold", ()),
            hard_negatives=spec.get("hard_negatives", ()),
        )
        for name, spec in slices.items()
    }
