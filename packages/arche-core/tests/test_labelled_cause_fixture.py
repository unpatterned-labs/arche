# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""arche against a world where every disagreement says why it happened.

This is the one benchmark in this repository whose pairs are labelled with the
*reason* two records differ, and the reason is what makes it worth having:

``change``
    The supplier moved, the director resigned, the account was replaced. **Both
    records were true** when they were written.
``representation``
    The same fact encoded differently: a dropped legal suffix, a source that
    stores names in capitals, a lost diacritic.
``error``
    A typo, an OCR misread, a truncation. One record is a distortion.

A matcher tuned only against the third kind learns that all disagreement means
"different entity", and then splits an entity the first time it legitimately
changes. Public entity-resolution benchmarks produce only the third kind,
because producing the first means modelling an entity's life rather than adding
noise to a string.

**Why a committed fixture rather than a dependency.** The generator lives in its
own repository, which is private, and is not published to PyPI. A public
repository whose tests need a private package is broken for every contributor
and for CI. What travels instead is the file contract, which is the generator's
actual product: Parquet plus a manifest, read here with ``pyarrow`` and nothing
else. Exercising it that way is worth more than the convenience of an import,
because it is the same path somebody else's matcher takes.

**What these numbers are for.** Catching a regression, and nothing else. 60
organisations is far too small to say how good a matcher is: recall moves by
tenths on a single seed. The thresholds below are deliberately loose floors
around the measured values, so they fail when something breaks rather than when
a comparator is tuned. `FIXTURE.md` beside the data says the same thing.
"""

from __future__ import annotations

import collections
from pathlib import Path

import arche
import pytest

pytest.importorskip("pyarrow")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ng_supplier_fixture"

pytestmark = pytest.mark.skipif(
    not (FIXTURE / "observations.parquet").is_file(),
    reason="the synthetic fixture is not in this checkout",
)


def _table(name: str) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(FIXTURE / f"{name}.parquet").to_pylist()


@pytest.fixture(scope="module")
def world() -> dict:
    """The fixture, split into what a matcher may see and what it may not."""
    truth_rows = _table("truth")
    return {
        "observations": _table("observations"),
        "truth": {r["record_id"]: r["truth_entity_id"] for r in truth_rows},
        "differences": _table("differences"),
    }


# ── the contract the fixture is supposed to keep ─────────────────────────────


def test_the_answer_key_is_not_in_the_matchers_input(world: dict):
    """A truth column in the observations would make the benchmark meaningless.

    The generator refuses this at write time rather than in a test, but this
    repository receives files rather than calling the generator, so it checks
    what it was given.
    """
    forbidden = {"entity_id", "truth_entity_id", "truth", "state_index",
                 "difference_kind", "cause", "event_id", "applied"}
    present = set(world["observations"][0])
    assert not (present & forbidden), (
        f"the matcher's input carries truth columns {sorted(present & forbidden)}"
    )


def test_the_record_id_does_not_encode_the_entity(world: dict):
    """It is a content hash, so the truth is not derivable by string work."""
    by_entity = collections.defaultdict(set)
    for record_id, entity in world["truth"].items():
        assert not record_id.startswith(entity), record_id
        by_entity[entity].add(record_id)
    shared = [e for e, ids in by_entity.items() if len(ids) > 1]
    assert shared, "no entity is observed twice, so there is nothing to resolve"


def test_all_three_kinds_of_disagreement_are_present(world: dict):
    kinds = collections.Counter(d["difference_kind"] for d in world["differences"])
    assert set(kinds) == {"change", "representation", "error"}, (
        f"the fixture lost a difference kind: {dict(kinds)}. `change` is the one "
        "no public benchmark has, and the reason this fixture exists."
    )
    assert kinds["change"] >= 10, f"too few change pairs to mean anything: {kinds}"


# ── arche against it ─────────────────────────────────────────────────────────


def _score(observations: list[dict], truth: dict[str, str]) -> dict:
    """Run the organisation pack over the fixture and score it against truth."""
    records = [{**o, "id": o["record_id"]} for o in observations]
    result = arche.reconcile(records, records, entity="organisation", id_field="id")

    merged, reviewed = set(), set()
    for edge in result["matches"]:
        a, b = str(edge["a_id"]), str(edge["b_id"])
        if a == b:
            continue
        pair = (a, b) if a < b else (b, a)
        (merged if edge["decision"] == "match" else reviewed).add(pair)

    ids = sorted(truth)
    true_pairs = {
        (a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
        if truth[a] == truth[b]
    }
    hits = merged & true_pairs
    return {
        "precision": len(hits) / len(merged) if merged else 0.0,
        "recall": len(hits) / len(true_pairs),
        "coverage": len((merged | reviewed) & true_pairs) / len(true_pairs),
        "true_pairs": len(true_pairs),
        "merged": len(merged),
    }


@pytest.fixture(scope="module")
def scored(world: dict) -> dict:
    return _score(world["observations"], world["truth"])


def test_arche_resolves_this_world_about_as_well_as_it_did(scored: dict):
    """Loose floors. They fail on a break, not on a tuning change.

    Measured when written, on 168 observations and 182 true pairs: precision
    1.0000, recall 0.6044, coverage 0.9231, 110 pairs merged. The floors sit well
    below that because 60 organisations is a small sample and a comparator change
    can legitimately move a tenth.

    Precision of exactly 1.0 is a property of this sample, not a promise. It is
    why the floor is 0.90: a single false merge on 110 would take it to 0.991,
    which must not fail a build.
    """
    assert scored["true_pairs"] > 50, "the fixture stopped having pairs to find"
    assert scored["precision"] >= 0.90, scored
    assert scored["recall"] >= 0.50, scored


def test_coverage_exceeds_recall_because_arche_abstains(scored: dict):
    """The third answer is the point, and it has to show up in a measurement.

    arche can say `review` rather than merging or splitting. An engine with
    three answers scored as though it had two is scored wrongly, so `coverage`
    counts pairs surfaced for review as well as merged. If these two are ever
    equal, either abstention stopped working or the scoring collapsed it.
    """
    assert scored["coverage"] > scored["recall"], scored


def test_the_change_stratum_is_harder_than_the_representation_one(world: dict, scored: dict):
    """The finding the labelled causes exist to expose.

    A legitimately changed attribute is read as evidence *against* identity by
    anything that compares it, so pairs that differ because the supplier moved
    are harder than pairs that differ because a source abbreviated a suffix.
    This asserts the ordering, not a level: the ordering is the claim that
    survives a small sample.
    """
    records = [{**o, "id": o["record_id"]} for o in world["observations"]]
    result = arche.reconcile(records, records, entity="organisation", id_field="id")
    merged = set()
    for edge in result["matches"]:
        a, b = str(edge["a_id"]), str(edge["b_id"])
        if a != b and edge["decision"] == "match":
            merged.add((a, b) if a < b else (b, a))

    found: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for d in world["differences"]:
        a, b = d["observation_a"], d["observation_b"]
        pair = (a, b) if a < b else (b, a)
        tally = found[d["difference_kind"]]
        tally[0] += pair in merged
        tally[1] += 1

    rates = {kind: hit / total for kind, (hit, total) in found.items() if total}
    assert rates["change"] < rates["representation"], (
        f"a legitimate change should be harder to link than a re-spelling: {rates}"
    )
