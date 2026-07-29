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

"""E1: reconciliation metrics harness (`arche.resolve.metrics`)."""

from arche.resolve.metrics import evaluate, evaluate_slices


def _m(a, b, decision):
    return {"a_id": a, "b_id": b, "decision": decision, "score": 0.9}


def test_perfect_run():
    matches = [_m("A1", "B1", "match"), _m("A2", "B2", "match")]
    gold = [("A1", "B1"), ("A2", "B2")]
    r = evaluate(matches, gold)
    assert r["precision"] == 1.0 and r["recall"] == 1.0 and r["f1"] == 1.0
    assert r["false_merge_rate"] == 0.0


def test_false_merge_is_caught():
    # A1<->B2 is a hard negative that got auto-matched -> false merge.
    matches = [_m("A1", "B1", "match"), _m("A1", "B2", "match")]
    gold = [("A1", "B1")]
    r = evaluate(matches, gold, hard_negatives=[("A1", "B2")])
    assert r["false_merge_rate"] == 1.0
    assert ("A1", "B2") in r["false_merges"]
    assert r["precision"] == 0.5  # one of two matches was wrong


def test_review_does_not_count_as_match_but_surfaces():
    # The gate routed the near-dup to review: no false merge, but it surfaced.
    matches = [_m("A1", "B1", "match"), _m("A1", "B2", "review")]
    gold = [("A1", "B1")]
    r = evaluate(matches, gold, hard_negatives=[("A1", "B2")])
    assert r["false_merge_rate"] == 0.0   # review is not a merge
    assert r["review_queue"] == 1
    assert r["precision"] == 1.0


def test_surfaced_recall_counts_review():
    # The true pair only reached 'review' — recall (match) is 0 but it surfaced.
    matches = [_m("A1", "B1", "review")]
    gold = [("A1", "B1")]
    r = evaluate(matches, gold)
    assert r["recall"] == 0.0
    assert r["surfaced_recall"] == 1.0
    assert r["false_negatives"] == 1


def test_missing_pair_is_a_false_negative():
    matches = []
    gold = [("A1", "B1")]
    r = evaluate(matches, gold)
    assert r["false_negatives"] == 1
    assert r["recall"] == 0.0
    assert r["surfaced_recall"] == 0.0


def test_evaluate_slices_breaks_out_per_slice():
    matches = [_m("A1", "B1", "match"), _m("A2", "B2", "review")]
    slices = {
        "transliteration": {"gold": [("A1", "B1")]},
        "near_dup_negative": {"gold": [], "hard_negatives": [("A2", "B2")]},
    }
    out = evaluate_slices(matches, slices)
    assert out["transliteration"]["recall"] == 1.0
    # A2<->B2 was review, not match -> no false merge on the negative slice
    assert out["near_dup_negative"]["false_merge_rate"] == 0.0
