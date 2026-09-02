# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""M0 runtime foundation contracts."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime

import arche
import pytest
from arche.runtime import DecisionReceipt, Entity, Evidence, Observation, new_entity_id


@pytest.fixture
def runtime():
    """An isolated local runtime with the optional DuckDB extra installed."""
    pytest.importorskip("duckdb")
    engine = arche.attach("duckdb:///:memory:")
    yield engine
    engine.store.close()


def test_attach_returns_a_usable_duckdb_runtime(runtime):
    """The public entry point gives callers an initialised local store."""
    runtime.store.ensure_schema()
    assert type(runtime.store).__name__ == "DuckDBStore"


def test_schema_initialisation_is_idempotent(runtime):
    """A caller may safely attach or initialise an existing store twice."""
    runtime.store.ensure_schema()
    runtime.store.ensure_schema()


def test_runtime_persists_stable_entity_observation_evidence_and_decision(runtime):
    """The M0 contracts round-trip without consulting a resolver or network."""
    timestamp = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    entity = Entity(new_entity_id(), "organisation", "legal_entity", timestamp)
    observation = Observation(
        "obs_01", "supplier_registry", "supplier-7", timestamp, "sha256:abc"
    )
    evidence = Evidence(
        "ev_01",
        observation.observation_id,
        "registration_id",
        "supports",
        {"source": "registry"},
    )
    receipt = DecisionReceipt(
        "dec_01",
        "same_entity",
        "link",
        (evidence.evidence_id,),
        timestamp,
        raw_score=0.99,
        probability=0.98,
        policy_pin="supplier-v1",
        schema_pin="organisation-v1",
    )

    runtime.store.write_entities([entity])
    runtime.store.write_observations([observation])
    runtime.store.write_evidence([evidence])
    runtime.store.write_decisions([receipt])

    assert runtime.store.get_entity(entity.entity_id) == entity
    assert runtime.store.get_observation(observation.observation_id) == observation
    assert runtime.store.get_evidence(evidence.evidence_id) == evidence
    assert runtime.store.get_decision(receipt.decision_id) == receipt


def test_entity_identity_does_not_change_with_revisable_state(runtime):
    """Entity identity is opaque, not a hash of state that will later change."""
    entity = Entity(
        new_entity_id(),
        "organisation",
        "legal_entity",
        datetime(2026, 9, 2, tzinfo=UTC),
    )
    revised = replace(entity, status="inactive")

    runtime.store.write_entities([entity])

    assert entity.entity_id == revised.entity_id
    assert entity.entity_id.startswith("ent_")
    assert len(entity.entity_id) == len("ent_") + 32


def test_failed_entity_batch_rolls_back_without_a_partial_write(runtime):
    """A duplicate identity cannot leave earlier rows from the same batch behind."""
    import duckdb

    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    existing = Entity("ent_existing", "organisation", "legal_entity", timestamp)
    new_entity = Entity("ent_new", "organisation", "legal_entity", timestamp)
    runtime.store.write_entities([existing])

    with pytest.raises(duckdb.ConstraintException):
        runtime.store.write_entities([new_entity, existing])

    assert runtime.store.get_entity(new_entity.entity_id) is None


def test_attach_rejects_unknown_store_uri_before_opening_a_connection():
    """Callers receive an actionable error instead of an implicit backend choice."""
    with pytest.raises(ValueError, match="duckdb:///"):
        arche.attach("sqlite:///arche.db")


def test_importing_arche_does_not_eagerly_import_duckdb():
    """The new optional store keeps the existing cold-import boundary intact."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import arche; assert 'duckdb' not in sys.modules"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
