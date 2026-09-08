# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""The synthetic world's ground truth, and the invariants that make it worth scoring.

Guards `data/synthetic/`. Not the benchmark itself -- that runs from
`build_ng_supplier_v0.py` -- but the claims the dataset makes about itself:

* it is reproducible under its seed, and a different seed is a different world;
* it does not ship the answer inside the question (no truth column, no entity
  id recoverable from a record id);
* every observation maps to exactly one entity;
* **a legitimate change is never labelled an error**, which is the whole reason
  this exists;
* the identifiers are valid by construction, so a miss is the matcher's.

The world is generated once per module at small scale. It is seeded, so these
are deterministic tests, not sampling.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SYNTHETIC = REPO / "data" / "synthetic"

pytestmark = pytest.mark.skipif(
    not (SYNTHETIC / "arche_synthetic" / "__init__.py").exists(),
    reason="data/synthetic is not present in this checkout",
)

SMALL = {"organisations": 120, "people": 160, "places": 80}


@pytest.fixture(scope="module")
def synthetic():
    if str(SYNTHETIC) not in sys.path:
        sys.path.insert(0, str(SYNTHETIC))
    if importlib.util.find_spec("arche_synthetic") is None:  # pragma: no cover
        pytest.skip("arche_synthetic not importable")
    import arche_synthetic

    return arche_synthetic


@pytest.fixture(scope="module")
def world(synthetic):
    built, _ = synthetic.build("ng_supplier_v0", seed=7, scale=SMALL)
    return built


@pytest.fixture(scope="module")
def written(synthetic, tmp_path_factory):
    out = tmp_path_factory.mktemp("world")
    _, manifest = synthetic.build("ng_supplier_v0", seed=7, scale=SMALL, out=out)
    return out, manifest


class TestReproducibility:
    """AT-006. A benchmark nobody can regenerate is an anecdote."""

    def test_the_same_seed_is_the_same_world(self, synthetic, tmp_path):
        _, a = synthetic.build("ng_supplier_v0", seed=7, scale=SMALL, out=tmp_path / "a")
        _, b = synthetic.build("ng_supplier_v0", seed=7, scale=SMALL, out=tmp_path / "b")
        assert a["content_fingerprints"] == b["content_fingerprints"]
        assert set(a["content_fingerprints"]) == {"observations", "truth",
                                                  "differences", "events"}

    def test_a_different_seed_is_a_different_world(self, synthetic, tmp_path):
        _, a = synthetic.build("ng_supplier_v0", seed=7, scale=SMALL, out=tmp_path / "a")
        _, b = synthetic.build("ng_supplier_v0", seed=8, scale=SMALL, out=tmp_path / "b")
        assert a["content_fingerprints"] != b["content_fingerprints"]

    def test_the_manifest_records_what_would_be_needed_to_rebuild(self, written):
        _, manifest = written
        assert manifest["seed"] == 7
        assert manifest["generator_version"]
        assert manifest["world_pack"] == "ng_supplier_v0"
        assert manifest["provenance"]


class TestTheAnswerIsNotInTheQuestion:
    """The invariant a benchmark cannot be trusted without."""

    def test_observations_carry_no_truth_column(self, written, synthetic):
        out, _ = written
        import pyarrow.parquet as pq

        columns = set(pq.read_table(out / "observations.parquet").column_names)
        assert not columns & set(synthetic.export.FORBIDDEN)
        assert "record_id" in columns

    def test_a_truth_column_is_refused_at_write_time(self, synthetic, world):
        """Not only tested -- refused. A test can be deleted; the writer cannot."""
        rows = [{"record_id": "rec_1", "entity_id": "syn:organisation:000001"}]
        with pytest.raises(synthetic.export.LeakError, match="truth column"):
            synthetic.export.check_no_leak(rows, world)

    def test_an_entity_id_leaking_through_a_value_is_refused(self, synthetic, world):
        """A column-name check alone would not catch this one."""
        leaked = next(iter(world.entities))
        rows = [{"record_id": "rec_1", "name": leaked}]
        with pytest.raises(synthetic.export.LeakError, match="leaks entity id"):
            synthetic.export.check_no_leak(rows, world)

    def test_record_ids_hold_no_entity_information(self, world, synthetic):
        """Opaque by construction: the entity was never in the hashed payload.

        Checked three ways, because this is the invariant whose failure would
        silently invalidate every number measured on the set.
        """
        import re

        shape = re.compile(r"^rec_[0-9a-f]{16}$")
        suffixes = {e.rsplit(":", 1)[-1] for e in world.entities}
        for observation in world.observations:
            assert shape.match(observation.record_id)
            assert observation.entity_id not in observation.record_id
            assert not any(s in observation.record_id[4:] for s in suffixes)

        # And the id function takes no entity argument at all -- the strongest
        # form of the guarantee, since there is nothing to leak.
        import inspect

        parameters = inspect.signature(synthetic.ids.record_id).parameters
        assert list(parameters) == ["world_id", "source", "sequence"]

    def test_record_ids_are_unique(self, world):
        ids = [o.record_id for o in world.observations]
        assert len(ids) == len(set(ids))


class TestTruthCompleteness:
    """AT-008."""

    def test_every_observation_maps_to_exactly_one_entity(self, written, world):
        out, _ = written
        import pyarrow.parquet as pq

        truth = pq.read_table(out / "truth.parquet").to_pylist()
        observations = pq.read_table(out / "observations.parquet").to_pylist()
        mapping = {r["record_id"]: r["truth_entity_id"] for r in truth}
        assert len(mapping) == len(truth)
        assert {o["record_id"] for o in observations} == set(mapping)
        assert set(mapping.values()) <= set(world.entities)

    def test_every_difference_joins_two_observations_of_one_entity(self, world):
        by_id = {o.record_id: o for o in world.observations}
        for d in world.differences:
            a, b = by_id[d.observation_a], by_id[d.observation_b]
            assert a.entity_id == b.entity_id == d.entity_id
            assert a.record_id != b.record_id

    def test_every_change_names_an_event_that_exists(self, world):
        events = {e.event_id for e in world.events}
        changes = [d for d in world.differences if d.difference_kind == "change"]
        assert changes, "no legitimate change was generated at all"
        for d in changes:
            assert d.event_id in events


class TestChangeIsNotError:
    """AT-001 and AT-005 -- the claim the whole dataset is built to support."""

    def test_an_entity_that_moves_keeps_one_identity_and_gains_a_state(self, world):
        moved = [e for e, chain in world.states.items() if len(chain) > 1]
        assert moved, "no entity changed state"
        for entity_id in moved:
            chain = world.states[entity_id]
            assert world.entities[entity_id].entity_type
            # states tile the timeline, in order, without a gap
            for earlier, later in zip(chain, chain[1:], strict=False):
                assert earlier.valid_to == later.valid_from
                assert earlier.valid_from < earlier.valid_to
            assert chain[-1].valid_to is None

    def test_no_lifecycle_change_is_labelled_an_error(self, world):
        """The failure this dataset exists to make visible.

        A stale ERP address is not a typo. If the generator ever labels one as
        an error, every number measured on the `legitimate_change` stratum is
        wrong in the direction that flatters a matcher.
        """
        by_id = {o.record_id: o for o in world.observations}
        observer = _observer(world)
        changes = {(d.observation_a, d.observation_b, d.attribute)
                   for d in world.differences if d.difference_kind == "change"}
        checked = 0
        for pair in {(d.observation_a, d.observation_b) for d in world.differences}:
            a, b = by_id[pair[0]], by_id[pair[1]]
            if a.state_index == b.state_index:
                continue
            # Independent of the generator's own event lookup: compare the TRUE
            # values of the two states these records saw. If they differ, the
            # pair must carry a `change` row for that attribute -- whatever
            # corruption was layered on top.
            truth_a = observer._flatten(world.states[a.entity_id][a.state_index].attributes)
            truth_b = observer._flatten(world.states[b.entity_id][b.state_index].attributes)
            for attribute in set(a.attributes) & set(b.attributes):
                if truth_a.get(attribute) == truth_b.get(attribute):
                    continue
                checked += 1
                assert (*pair, attribute) in changes, (
                    f"{attribute} genuinely differs between the states "
                    f"{a.record_id} and {b.record_id} saw, but the pair carries "
                    "no `change` row -- a legitimate change has been filed as noise")
        assert checked, "no pair straddled a real change; the test proved nothing"

    def test_the_stale_source_is_the_one_that_lags(self, world):
        """The ERP should be the source most often looking at an older state."""
        stale = {"erp": 0, "registry": 0, "invoice": 0}
        for o in world.observations:
            if o.state_index < len(world.states[o.entity_id]) - 1:
                stale[o.source] += 1
        assert stale["erp"] > stale["registry"]


class TestRepresentationIsNotError:
    """AT-002 and AT-003."""

    def test_a_legal_suffix_rewrite_is_representation(self, synthetic):
        import random
        rewritten = synthetic.observe.REPRESENTATION["legal_suffix_abbreviated"](
            "Okafor Engineering Limited", random.Random(0))
        assert rewritten == "Okafor Engineering Ltd"
        kinds = {d.difference_kind for d in _by_cause(synthetic, "legal_suffix_abbreviated")}
        assert kinds == {"representation"}

    def test_dropping_a_suffix_is_representation(self, synthetic):
        import random
        assert synthetic.observe.REPRESENTATION["legal_suffix_dropped"](
            "Okafor Engineering Limited", random.Random(0)) == "Okafor Engineering"

    def test_an_ocr_substitution_is_an_error_with_its_cause(self, synthetic, world):
        import random
        broken = synthetic.observe.CORRUPTION["ocr_confusion"](
            "OKAFOR", random.Random(1))
        assert broken != "OKAFOR"
        ocr = [d for d in world.differences if d.cause == "ocr_confusion"]
        assert ocr and {d.difference_kind for d in ocr} == {"error"}

    def test_the_three_kinds_are_the_whole_vocabulary(self, world):
        assert ({d.difference_kind for d in world.differences}
                == {"change", "representation", "error"})

    def test_house_style_is_consistent_across_a_record(self, world):
        """An ERP that stores NAMES IN CAPITALS stores addresses in capitals too.

        Rolling case per field produced records that shouted one column and
        whispered the next, which inflated the representation stratum with
        differences no matcher would ever see.
        """
        for o in world.observations:
            upper = {name for name, notes in o.applied.items()
                     if any(c == "case_upper" for _, c in notes)}
            if not upper:
                continue
            eligible = {name for name, value in o.attributes.items()
                        if isinstance(value, str) and value != value.upper()}
            assert not eligible, (
                f"{o.record_id} upper-cased {sorted(upper)} but left "
                f"{sorted(eligible)} in mixed case")


class TestValidByConstruction:
    """A benchmark whose identifiers fail the validator measures the generator."""

    def test_the_local_validators_agree_with_arches(self, synthetic):
        """The package carries its own RC/TIN format checks so it can generate a
        world with nothing else installed. arche has the same two. Asserting
        they still agree is stronger than depending on either alone: a one-sided
        import would hide a drift, and a drift means the benchmark's identifiers
        stop being the ones arche's detectors were built to read.
        """
        from arche.detect.ng.ids import _validate_ng_rc, _validate_ng_tin

        cases = ["RC123456", "BN99999999", "RC1234", "rc 123456", "RC12345678",
                 "XX123456", "RC", "", "12345678901234567"]
        for text in cases:
            assert synthetic.world.valid_rc(text) == _validate_ng_rc(text)[0], text
        for text in ["1234567890", "12345678901234", "123", "12345678901",
                     "1234-5678-90", "abcdefghij", ""]:
            assert synthetic.world.valid_tin(text) == _validate_ng_tin(text)[0], text

    def test_the_lexicon_is_vendored_so_the_package_stands_alone(self, synthetic):
        """`pip install arche-synthetic` must generate a world with nothing else
        installed; a name pool reachable only through arche would break that."""
        from pathlib import Path as _Path

        vendored = _Path(synthetic.world.__file__).parent / "data" / "african_names_v1.jsonl.gz"
        assert vendored.exists()
        assert synthetic.world._lexicon_path() == vendored

    def test_every_rc_number_and_tin_passes_arches_validator(self, world):
        from arche.detect.ng.ids import _validate_ng_rc, _validate_ng_tin

        for entity in world.of_type("organisation"):
            attributes = world.current(entity.entity_id).attributes
            assert _validate_ng_rc(attributes["rc_number"])[0]
            assert _validate_ng_tin(attributes["tin"])[0]

    def test_the_name_pool_excludes_what_is_not_a_name(self, synthetic):
        """5.8% of the shipped lexicon is Wikidata URLs and property labels."""
        usable = synthetic.world._usable
        assert not usable("http://www.wikidata.org/.well-known/genid/25884cc")
        assert not usable("Abas (nom de famille)")
        assert not usable("njirimara ezinụlọnjirimara ezinụlọ")
        assert not usable("Baale Amulegbaro Jagun Oninlo Estate")
        assert usable("Okonkwo")
        assert usable("Abdul Sattar")

    def test_common_names_actually_collide(self, world):
        """Uniform names make a benchmark easy in a way real data never is.

        This is the gap the frequency work exists to close: without collisions
        a name match is very nearly a key, and the matcher is not being asked
        the hard question.
        """
        from collections import Counter

        heads = Counter(world.current(e.entity_id).attributes["legal_name"].split()[0]
                        for e in world.of_type("organisation"))
        shared = sum(n for n in heads.values() if n > 1)
        assert shared >= len(world.of_type("organisation")) * 0.15


def _observer(world):
    """The flattening logic, to read a state the way an observation would."""
    import arche_synthetic

    return arche_synthetic.observe.Observer(world, seed=0)


def _by_cause(synthetic, cause: str):
    built, _ = synthetic.build("ng_supplier_v0", seed=7, scale=SMALL)
    return [d for d in built.differences if d.cause == cause]
