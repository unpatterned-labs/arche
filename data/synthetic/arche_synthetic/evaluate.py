# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Scoring a matcher against a world whose disagreements are labelled.

    from evaluate import Benchmark, Predictions

    bench = Benchmark.load(Path("worlds/ng_supplier_v0"))
    report = bench.score(Predictions(arm="exact", pairs=..., candidates=...))

**The one thing to get right: precision does not stratify.**

`differences.parquet` only ever describes pairs of records *of the same
entity* -- a "difference" is a disagreement between two views of one thing. So
a false merge, which joins records of two *different* entities, has no
difference row and belongs to no stratum. "Precision on the legitimate-change
stratum" is not a quantity that exists, and a report that prints one is
inventing a number that looks authoritative and means nothing.

Therefore:

* **recall is the stratified axis** -- of the true pairs that differ because
  the supplier moved, how many did the matcher find? That is well defined, and
  it is the number this whole benchmark exists to produce;
* **precision is reported once, overall**;
* **false merges get their own taxonomy**, by what the two records shared --
  the same surname head, the same city, the same bank. That is the honest way
  to say "this matcher fails on common names", and it is where a stratified
  precision column would have gone.

The same trap sank an earlier arche benchmark from the other side: the London
hospitals set can measure recall and cannot measure precision, because its
truth labels are structurally incomplete. Different cause, same discipline --
say which axis a set can carry, and refuse the other.

**Score each arm on the vocabulary it emits.** arche's crosswalk returns
`decision in {match, review}` and its gate demotes a pair to `review` *without
lowering the score*, so cutting the arche arm at `score >= 0.7` once reported
398 false merges where the engine's own decision reported 2. Splink emits a
probability and no decision, so it gets a probability cut. An arm supplies the
positive set it stands behind; this module never re-derives one from scores.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Pair = tuple[str, str]


def pair(a: str, b: str) -> Pair:
    """A pair as an unordered key, so (a,b) and (b,a) are one thing."""
    return (a, b) if a <= b else (b, a)


@dataclass
class Predictions:
    """What one matcher claims, in its own vocabulary.

    ``pairs`` is the set of *positive* claims -- the pairs this arm stands
    behind, however it decided. ``abstentions`` are pairs it surfaced and
    declined to assert (arche's ``review``); they are reported, never scored as
    either right or wrong, because an abstention is a third answer and folding
    it into one of the other two would make it decorative.
    """

    arm: str
    pairs: set[Pair]
    candidates: set[Pair] = field(default_factory=set)
    clusters: list[list[str]] | None = None
    abstentions: set[Pair] = field(default_factory=set)
    seconds: float = 0.0
    notes: dict[str, Any] = field(default_factory=dict)


def _components(records: list[str], pairs: set[Pair]) -> list[list[str]]:
    """Transitive closure over the positive pairs: the implied clustering."""
    parent = {r: r for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, list[str]] = defaultdict(list)
    for r in records:
        groups[find(r)].append(r)
    return list(groups.values())


@dataclass
class Benchmark:
    """A generated world, loaded as truth to score against."""

    world: Path
    observations: list[dict[str, Any]]
    truth: dict[str, str]                       # record_id -> entity_id
    by_entity: dict[str, list[str]]
    true_pairs: set[Pair]
    by_kind: dict[str, set[Pair]]               # difference_kind -> true pairs
    by_cause: dict[str, set[Pair]]              # cause -> true pairs

    @classmethod
    def load(cls, world: Path) -> Benchmark:
        import pyarrow.parquet as pq

        observations = pq.read_table(world / "observations.parquet").to_pylist()
        truth = {r["record_id"]: r["truth_entity_id"]
                 for r in pq.read_table(world / "truth.parquet").to_pylist()}
        by_entity: dict[str, list[str]] = defaultdict(list)
        for record_id, entity in truth.items():
            by_entity[entity].append(record_id)

        true_pairs = set()
        for members in by_entity.values():
            members = sorted(members)
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    true_pairs.add(pair(a, b))

        by_kind: dict[str, set[Pair]] = defaultdict(set)
        by_cause: dict[str, set[Pair]] = defaultdict(set)
        for row in pq.read_table(world / "differences.parquet").to_pylist():
            key = pair(row["observation_a"], row["observation_b"])
            by_kind[row["difference_kind"]].add(key)
            by_cause[f"{row['difference_kind']}/{row['cause']}"].add(key)
        return cls(world, observations, truth, dict(by_entity), true_pairs,
                   dict(by_kind), dict(by_cause))

    # -- what two records share, for the false-merge taxonomy ----------------

    def _shared(self, a: str, b: str) -> list[str]:
        by_id = getattr(self, "_index", None)
        if by_id is None:
            by_id = self._index = {o["record_id"]: o for o in self.observations}
        ra, rb = by_id.get(a, {}), by_id.get(b, {})
        shared = []
        na, nb = (ra.get("name") or "").upper(), (rb.get("name") or "").upper()
        if na and nb and na.split()[:1] == nb.split()[:1]:
            shared.append("surname_head")
        if na and na == nb:
            shared.append("whole_name")
        for column in ("city", "bank", "phone", "address", "rc_number"):
            if ra.get(column) and ra.get(column) == rb.get(column):
                shared.append(column)
        return shared or ["nothing_obvious"]

    # -- scoring -------------------------------------------------------------

    def score(self, predictions: Predictions) -> dict[str, Any]:
        """The report for one arm."""
        claimed = {p for p in predictions.pairs if p[0] in self.truth and p[1] in self.truth}
        hits = claimed & self.true_pairs
        false = claimed - self.true_pairs
        precision = len(hits) / len(claimed) if claimed else 0.0
        recall = len(hits) / len(self.true_pairs) if self.true_pairs else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0

        # Recall by stratum. Precision deliberately absent -- see the module
        # docstring: a false merge belongs to no stratum, so there is no
        # denominator to put it over.
        strata = {}
        for name, pairs_in in sorted({**self.by_kind, **self.by_cause}.items()):
            true_here = pairs_in & self.true_pairs
            if not true_here:
                continue
            strata[name] = {
                "true_pairs": len(true_here),
                "recall": round(len(true_here & hits) / len(true_here), 4),
            }

        records = list(self.truth)
        clusters = predictions.clusters or _components(records, claimed)
        bcubed = self._bcubed(clusters)

        merged = [c for c in clusters
                  if len({self.truth[r] for r in c if r in self.truth}) > 1]
        entity_clusters: dict[str, set[int]] = defaultdict(set)
        for i, c in enumerate(clusters):
            for r in c:
                if r in self.truth:
                    entity_clusters[self.truth[r]].add(i)
        split = [e for e, cs in entity_clusters.items() if len(cs) > 1]

        taxonomy = Counter()
        for a, b in false:
            for label in self._shared(a, b):
                taxonomy[label] += 1

        report: dict[str, Any] = {
            "arm": predictions.arm,
            "seconds": round(predictions.seconds, 2),
            "overall": {
                "claimed_pairs": len(claimed),
                "true_pairs": len(self.true_pairs),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                # An engine that can say "a person should look at this" is not
                # comparable on recall alone to one that can only say yes or
                # no. `recall` counts automatic merges; `coverage` counts the
                # true pairs it either merged OR surfaced for review. Reporting
                # only the first understates every engine with a refusal
                # mechanism, which is most of the reason arche has one.
                "abstentions": len(predictions.abstentions),
                "coverage": round(
                    len((claimed | predictions.abstentions) & self.true_pairs)
                    / len(self.true_pairs), 4) if self.true_pairs else 0.0,
            },
            "bcubed": bcubed,
            "recall_by_stratum": strata,
            "entities": {
                "clusters": len(clusters),
                "true_entities": len(self.by_entity),
                "false_merge_clusters": len(merged),
                "false_merge_rate": round(len(merged) / len(clusters), 4) if clusters else 0.0,
                "false_split_entities": len(split),
                "false_split_rate": round(len(split) / len(self.by_entity), 4),
            },
            "false_merges_by_what_was_shared": dict(taxonomy.most_common()),
            "blocking": self._blocking(predictions),
            "notes": predictions.notes,
        }
        return report

    def _bcubed(self, clusters: list[list[str]]) -> dict[str, float]:
        """Cluster quality per record, averaged. Handles singletons correctly."""
        cluster_of = {r: i for i, c in enumerate(clusters) for r in c}
        sizes = {i: len(c) for i, c in enumerate(clusters)}
        precision = recall = 0.0
        n = 0
        for record, entity in self.truth.items():
            if record not in cluster_of:
                continue
            members = clusters[cluster_of[record]]
            same = sum(1 for m in members if self.truth.get(m) == entity)
            precision += same / sizes[cluster_of[record]]
            recall += same / len(self.by_entity[entity])
            n += 1
        precision, recall = (precision / n, recall / n) if n else (0.0, 0.0)
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4),
                "f1": round(f1, 4)}

    def _blocking(self, predictions: Predictions) -> dict[str, Any]:
        """What the arm's own blocker kept, and what it threw away.

        Reported per arm rather than over a shared candidate set: handing every
        arm the same candidates would measure the scorers and hide the
        blockers, and blocking recall is one of the gaps this dataset exists to
        close -- arche computes it (`reconcile(truth_pairs=)`) and exactly one
        benchmark passes it today, on a product catalogue.

        **It never falls back to the positive pairs.** An arm that does not
        enumerate its candidates gets ``measured: False``, or the figure it
        reported itself, clearly labelled as such. Defaulting to `pairs` would
        print the arm's *recall* under the heading "blocking recall" -- the two
        would be identical by construction, and the number would be a lie in
        the flattering direction.
        """
        total = len(self.truth) * (len(self.truth) - 1) / 2
        reported = predictions.notes.get("blocking_recall_reported_by_arche")
        if not predictions.candidates:
            if reported is None:
                return {"measured": False,
                        "why": "the arm does not enumerate its candidate pairs"}
            return {"measured": True, "source": "reported by the arm, not recomputed",
                    "recall": reported,
                    "candidate_pairs": predictions.notes.get("candidate_pairs"),
                    "reduction_ratio": (
                        round(1 - predictions.notes["candidate_pairs"] / total, 6)
                        if predictions.notes.get("candidate_pairs") and total else None)}
        kept = predictions.candidates & self.true_pairs
        return {
            "measured": True,
            "source": "recomputed from the candidate pairs the arm reported",
            "candidate_pairs": len(predictions.candidates),
            "recall": round(len(kept) / len(self.true_pairs), 4) if self.true_pairs else 0.0,
            "reduction_ratio": round(1 - len(predictions.candidates) / total, 6) if total else 0.0,
            "pairs_per_record": round(len(predictions.candidates) / len(self.truth), 3),
        }


def table(reports: list[dict[str, Any]], strata: tuple[str, ...] = (
        "change", "representation", "error")) -> str:
    """The comparison, as the plan's table. Empty cells mean not measured."""
    head = (f"{'arm':<16}{'P':>7}{'R':>7}{'F1':>7}{'cover':>7}   "
            + "".join(f"{s[:9]:>10}" for s in strata)
            + f"{'falseMrg':>10}{'blockR':>9}{'secs':>8}")
    lines = [head, "-" * len(head)]
    for r in reports:
        o = r["overall"]
        block = r["blocking"].get("recall")
        block = float("nan") if block is None else block
        cells = "".join(
            f"{r['recall_by_stratum'].get(s, {}).get('recall', float('nan')):>10.3f}"
            for s in strata)
        lines.append(
            f"{r['arm']:<16}{o['precision']:>7.3f}{o['recall']:>7.3f}{o['f1']:>7.3f}"
            f"{o['coverage']:>7.3f}   "
            f"{cells}{r['entities']['false_merge_rate']:>10.3f}"
            f"{block:>9.3f}{r['seconds']:>8.1f}")
    return "\n".join(lines)


__all__ = ["Benchmark", "Pair", "Predictions", "pair", "table"]
