"""Tests for the human review queue (arche.review)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from arche.extract import Entity
from arche.resolve import ResolvedEntity
from arche.workflow._review import ReviewCandidate, ReviewQueue


# ===================================================================
# Helpers
# ===================================================================


def _make_entity(text: str, etype: str = "PERSON", confidence: float = 0.9, **meta) -> Entity:
    return Entity(
        text=text,
        entity_type=etype,
        confidence=confidence,
        start=0,
        end=len(text),
        source="test",
        metadata=meta,
    )


def _make_resolved(
    canonical: str,
    aliases: list[str] | None = None,
    confidence: float = 0.75,
    sources: int = 2,
    match_reasons: list[str] | None = None,
    entities: list[Entity] | None = None,
) -> ResolvedEntity:
    """Build a ResolvedEntity for testing."""
    if aliases is None:
        aliases = []
    if match_reasons is None:
        match_reasons = ["merged_2_mentions"]
    if entities is None:
        entities = [
            _make_entity(canonical),
            _make_entity(aliases[0] if aliases else canonical + " Jr"),
        ]
    return ResolvedEntity(
        canonical_name=canonical,
        entity_type="PERSON",
        aliases=aliases,
        confidence=confidence,
        sources=sources,
        match_reasons=match_reasons,
        entities=entities,
    )


@pytest.fixture
def queue() -> ReviewQueue:
    """A fresh in-memory review queue with default thresholds."""
    return ReviewQueue(auto_accept=0.85, auto_reject=0.30)


@pytest.fixture
def sample_entities() -> list[Entity]:
    return [
        _make_entity("Fatima Abdullahi"),
        _make_entity("Fatoumata Abdoulaye"),
        _make_entity("David Mensah"),
    ]


@pytest.fixture
def sample_resolved_pending() -> list[ResolvedEntity]:
    """A resolved entity with confidence in the review band (0.30 < 0.72 < 0.85)."""
    return [
        _make_resolved(
            "Fatima Abdullahi",
            aliases=["Fatoumata Abdoulaye"],
            confidence=0.72,
            sources=2,
            match_reasons=["merged_2_mentions", "name_similarity:0.72"],
            entities=[
                _make_entity("Fatima Abdullahi"),
                _make_entity("Fatoumata Abdoulaye"),
            ],
        ),
    ]


@pytest.fixture
def sample_resolved_high() -> list[ResolvedEntity]:
    """A resolved entity above the auto-accept threshold."""
    return [
        _make_resolved(
            "Fatima Abdullahi",
            aliases=["Fatima Abdullahi"],
            confidence=0.95,
            sources=2,
            entities=[
                _make_entity("Fatima Abdullahi"),
                _make_entity("Fatima Abdullahi"),
            ],
        ),
    ]


@pytest.fixture
def sample_resolved_low() -> list[ResolvedEntity]:
    """A resolved entity below the auto-reject threshold."""
    return [
        _make_resolved(
            "Fatima Abdullahi",
            aliases=["David Mensah"],
            confidence=0.20,
            sources=2,
            entities=[
                _make_entity("Fatima Abdullahi"),
                _make_entity("David Mensah"),
            ],
        ),
    ]


# ===================================================================
# Queue creation
# ===================================================================


class TestQueueCreation:
    def test_default_thresholds(self):
        q = ReviewQueue()
        assert q.auto_accept == 0.85
        assert q.auto_reject == 0.30

    def test_custom_thresholds(self):
        q = ReviewQueue(auto_accept=0.90, auto_reject=0.20)
        assert q.auto_accept == 0.90
        assert q.auto_reject == 0.20

    def test_reject_ge_accept_raises(self):
        with pytest.raises(ValueError, match="auto_reject.*must be less than"):
            ReviewQueue(auto_accept=0.50, auto_reject=0.50)

    def test_reject_gt_accept_raises(self):
        with pytest.raises(ValueError, match="auto_reject.*must be less than"):
            ReviewQueue(auto_accept=0.50, auto_reject=0.70)

    def test_threshold_out_of_range_raises(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            ReviewQueue(auto_accept=1.5, auto_reject=0.30)

    def test_negative_threshold_raises(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            ReviewQueue(auto_accept=0.85, auto_reject=-0.10)

    def test_empty_queue(self, queue):
        assert len(queue) == 0
        assert queue.pending() == []
        assert queue.stats()["total"] == 0


# ===================================================================
# Ingestion routing
# ===================================================================


class TestIngestion:
    def test_ingest_pending_band(self, queue, sample_entities, sample_resolved_pending):
        counts = queue.ingest(sample_entities, sample_resolved_pending)
        assert counts["pending"] == 1
        assert counts["auto_approved"] == 0
        assert counts["auto_rejected"] == 0
        assert len(queue.pending()) == 1

    def test_ingest_auto_accept(self, queue, sample_entities, sample_resolved_high):
        counts = queue.ingest(sample_entities, sample_resolved_high)
        assert counts["auto_approved"] == 1
        assert counts["pending"] == 0
        assert len(queue.pending()) == 0

    def test_ingest_auto_reject(self, queue, sample_entities, sample_resolved_low):
        counts = queue.ingest(sample_entities, sample_resolved_low)
        assert counts["auto_rejected"] == 1
        assert counts["pending"] == 0

    def test_ingest_singleton_ignored(self, queue, sample_entities):
        """Single-mention entities (sources=1) should not create candidates."""
        resolved = [
            ResolvedEntity(
                canonical_name="David Mensah",
                entity_type="PERSON",
                aliases=[],
                confidence=0.75,
                sources=1,
                match_reasons=[],
                entities=[_make_entity("David Mensah")],
            ),
        ]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["pending"] == 0
        assert counts["auto_approved"] == 0
        assert counts["auto_rejected"] == 0
        assert len(queue) == 0

    def test_ingest_empty_entities(self, queue):
        counts = queue.ingest([], [])
        assert counts == {"auto_approved": 0, "auto_rejected": 0, "pending": 0}

    def test_ingest_multiple_clusters(self, queue, sample_entities):
        """Multiple merged clusters produce multiple candidates."""
        resolved = [
            _make_resolved("Fatima Abdullahi", confidence=0.72, sources=2),
            _make_resolved("David Mensah", confidence=0.60, sources=2),
        ]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["pending"] == 2
        assert len(queue.pending()) == 2

    def test_ingest_multi_member_cluster(self, queue, sample_entities):
        """A cluster with 3 members produces 2 pairwise candidates."""
        entities = [
            _make_entity("Fatima Abdullahi"),
            _make_entity("Fatoumata Abdoulaye"),
            _make_entity("Fatimah Abdullah"),
        ]
        resolved = [
            ResolvedEntity(
                canonical_name="Fatima Abdullahi",
                entity_type="PERSON",
                aliases=["Fatoumata Abdoulaye", "Fatimah Abdullah"],
                confidence=0.70,
                sources=3,
                match_reasons=["merged_3_mentions"],
                entities=entities,
            ),
        ]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["pending"] == 2  # 3 members -> 2 pairs (base + each other)

    def test_ingest_at_boundary_auto_accept(self, queue, sample_entities):
        """Confidence exactly at auto_accept should be auto-approved."""
        resolved = [_make_resolved("Test", confidence=0.85, sources=2)]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["auto_approved"] == 1

    def test_ingest_at_boundary_auto_reject(self, queue, sample_entities):
        """Confidence exactly at auto_reject should be auto-rejected."""
        resolved = [_make_resolved("Test", confidence=0.30, sources=2)]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["auto_rejected"] == 1


# ===================================================================
# Query
# ===================================================================


class TestQuery:
    def test_pending_sorted_by_confidence(self, queue, sample_entities):
        resolved = [
            _make_resolved("Low", confidence=0.40, sources=2),
            _make_resolved("High", confidence=0.80, sources=2),
            _make_resolved("Mid", confidence=0.60, sources=2),
        ]
        queue.ingest(sample_entities, resolved)
        pending = queue.pending()
        assert len(pending) == 3
        assert pending[0].confidence == 0.80
        assert pending[1].confidence == 0.60
        assert pending[2].confidence == 0.40

    def test_get_valid_id(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        fetched = queue.get(candidate.id)
        assert fetched.id == candidate.id

    def test_get_invalid_id(self, queue):
        with pytest.raises(KeyError, match="not found"):
            queue.get("nonexistent-id")

    def test_all_returns_everything(self, queue, sample_entities):
        resolved = [
            _make_resolved("A", confidence=0.95, sources=2),  # auto_approved
            _make_resolved("B", confidence=0.72, sources=2),  # pending
            _make_resolved("C", confidence=0.20, sources=2),  # auto_rejected
        ]
        queue.ingest(sample_entities, resolved)
        assert len(queue.all()) == 3


# ===================================================================
# Review actions
# ===================================================================


class TestReviewActions:
    def test_approve(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        result = queue.approve(candidate.id, reviewer="human_1", notes="Same person")
        assert result.status == "approved"
        assert result.reviewer == "human_1"
        assert result.notes == "Same person"
        assert result.reviewed_at != ""
        assert len(queue.pending()) == 0

    def test_reject(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        result = queue.reject(candidate.id, reviewer="human_1", notes="Different people")
        assert result.status == "rejected"
        assert result.reviewer == "human_1"
        assert len(queue.pending()) == 0

    def test_escalate(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        result = queue.escalate(candidate.id, reviewer="junior_1", notes="Unsure")
        assert result.status == "escalated"
        assert result.reviewer == "junior_1"
        assert len(queue.pending()) == 0

    def test_approve_escalated(self, queue, sample_entities, sample_resolved_pending):
        """Escalated candidates can be approved."""
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        queue.escalate(candidate.id, reviewer="junior_1")
        result = queue.approve(candidate.id, reviewer="senior_1", notes="Confirmed match")
        assert result.status == "approved"
        assert result.reviewer == "senior_1"

    def test_reject_escalated(self, queue, sample_entities, sample_resolved_pending):
        """Escalated candidates can be rejected."""
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        queue.escalate(candidate.id, reviewer="junior_1")
        result = queue.reject(candidate.id, reviewer="senior_1", notes="Not the same")
        assert result.status == "rejected"

    def test_cannot_approve_auto_approved(self, queue, sample_entities, sample_resolved_high):
        queue.ingest(sample_entities, sample_resolved_high)
        candidates = queue.all()
        auto_approved = [c for c in candidates if c.status == "auto_approved"]
        assert len(auto_approved) == 1
        with pytest.raises(ValueError, match="must be 'pending' or 'escalated'"):
            queue.approve(auto_approved[0].id)

    def test_cannot_reject_already_approved(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        queue.approve(candidate.id, reviewer="human_1")
        with pytest.raises(ValueError, match="must be 'pending' or 'escalated'"):
            queue.reject(candidate.id)

    def test_cannot_escalate_non_pending(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        queue.approve(candidate.id, reviewer="human_1")
        with pytest.raises(ValueError, match="must be 'pending'"):
            queue.escalate(candidate.id)

    def test_approve_nonexistent(self, queue):
        with pytest.raises(KeyError, match="not found"):
            queue.approve("nonexistent-id")


# ===================================================================
# Statistics
# ===================================================================


class TestStats:
    def test_stats_empty(self, queue):
        s = queue.stats()
        assert s["total"] == 0
        assert s["pending"] == 0

    def test_stats_after_ingest(self, queue, sample_entities):
        resolved = [
            _make_resolved("A", confidence=0.95, sources=2),  # auto_approved
            _make_resolved("B", confidence=0.72, sources=2),  # pending
            _make_resolved("C", confidence=0.20, sources=2),  # auto_rejected
        ]
        queue.ingest(sample_entities, resolved)
        s = queue.stats()
        assert s["total"] == 3
        assert s["auto_approved"] == 1
        assert s["pending"] == 1
        assert s["auto_rejected"] == 1

    def test_stats_after_review(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        queue.approve(candidate.id, reviewer="test")
        s = queue.stats()
        assert s["approved"] == 1
        assert s["pending"] == 0


# ===================================================================
# Export / Import round-trip
# ===================================================================


class TestExportImport:
    def test_export_creates_file(self, queue, sample_entities, sample_resolved_pending, tmp_path):
        queue.ingest(sample_entities, sample_resolved_pending)
        out = tmp_path / "reviews.json"
        count = queue.export_decisions(str(out))
        assert count == 1
        assert out.exists()

        data = json.loads(out.read_text())
        assert "candidates" in data
        assert "stats" in data
        assert "exported_at" in data
        assert len(data["candidates"]) == 1

    def test_import_restores_state(self, queue, sample_entities, sample_resolved_pending, tmp_path):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        queue.approve(candidate.id, reviewer="human_1", notes="Confirmed")

        out = tmp_path / "reviews.json"
        queue.export_decisions(str(out))

        # Import into a fresh queue
        new_queue = ReviewQueue()
        count = new_queue.import_decisions(str(out))
        assert count == 1
        assert len(new_queue) == 1
        imported = new_queue.all()[0]
        assert imported.status == "approved"
        assert imported.reviewer == "human_1"
        assert imported.notes == "Confirmed"

    def test_import_nonexistent_file(self, queue):
        with pytest.raises(FileNotFoundError):
            queue.import_decisions("/nonexistent/file.json")

    def test_round_trip_preserves_data(self, queue, sample_entities, tmp_path):
        """Full round-trip: ingest, review, export, import — all data preserved."""
        resolved = [
            _make_resolved("A", confidence=0.95, sources=2),
            _make_resolved("B", confidence=0.72, sources=2),
            _make_resolved("C", confidence=0.20, sources=2),
        ]
        queue.ingest(sample_entities, resolved)

        # Review the pending one
        pending = queue.pending()
        assert len(pending) == 1
        queue.reject(pending[0].id, reviewer="test", notes="Different")

        out = tmp_path / "roundtrip.json"
        queue.export_decisions(str(out))

        new_queue = ReviewQueue()
        new_queue.import_decisions(str(out))

        assert new_queue.stats() == queue.stats()
        assert len(new_queue) == len(queue)

    def test_export_empty_queue(self, queue, tmp_path):
        out = tmp_path / "empty.json"
        count = queue.export_decisions(str(out))
        assert count == 0
        data = json.loads(out.read_text())
        assert data["candidates"] == []


# ===================================================================
# Persistence (auto-save/load)
# ===================================================================


class TestPersistence:
    def test_persist_on_ingest(self, sample_entities, sample_resolved_pending, tmp_path):
        path = tmp_path / "queue.json"
        q1 = ReviewQueue(persistence_path=str(path))
        q1.ingest(sample_entities, sample_resolved_pending)
        assert path.exists()

        # Load into a new queue
        q2 = ReviewQueue(persistence_path=str(path))
        assert len(q2) == 1
        assert q2.pending()[0].confidence == 0.72

    def test_persist_on_review(self, sample_entities, sample_resolved_pending, tmp_path):
        path = tmp_path / "queue.json"
        q1 = ReviewQueue(persistence_path=str(path))
        q1.ingest(sample_entities, sample_resolved_pending)
        candidate = q1.pending()[0]
        q1.approve(candidate.id, reviewer="test")

        q2 = ReviewQueue(persistence_path=str(path))
        assert q2.stats()["approved"] == 1
        assert q2.stats()["pending"] == 0

    def test_persist_on_clear(self, sample_entities, sample_resolved_pending, tmp_path):
        path = tmp_path / "queue.json"
        q1 = ReviewQueue(persistence_path=str(path))
        q1.ingest(sample_entities, sample_resolved_pending)
        q1.clear()

        q2 = ReviewQueue(persistence_path=str(path))
        assert len(q2) == 0


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    def test_candidate_repr(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        r = repr(candidate)
        assert "ReviewCandidate" in r
        assert "pending" in r

    def test_queue_repr(self, queue):
        r = repr(queue)
        assert "ReviewQueue" in r
        assert "auto_accept=0.85" in r

    def test_clear_removes_all(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        assert len(queue) > 0
        queue.clear()
        assert len(queue) == 0
        assert queue.pending() == []

    def test_candidate_to_dict(self, queue, sample_entities, sample_resolved_pending):
        queue.ingest(sample_entities, sample_resolved_pending)
        candidate = queue.pending()[0]
        d = candidate.to_dict()
        assert "id" in d
        assert "record_a" in d
        assert "record_b" in d
        assert "confidence" in d
        assert "status" in d
        assert d["status"] == "pending"

    def test_ingest_idempotent_candidates(self, queue, sample_entities, sample_resolved_pending):
        """Calling ingest twice adds new candidates (not idempotent — each call creates new UUIDs)."""
        queue.ingest(sample_entities, sample_resolved_pending)
        queue.ingest(sample_entities, sample_resolved_pending)
        assert len(queue) == 2

    def test_boundary_confidence_just_above_reject(self, queue, sample_entities):
        """Confidence just above auto_reject (0.31) should be pending."""
        resolved = [_make_resolved("Test", confidence=0.31, sources=2)]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["pending"] == 1

    def test_boundary_confidence_just_below_accept(self, queue, sample_entities):
        """Confidence just below auto_accept (0.84) should be pending."""
        resolved = [_make_resolved("Test", confidence=0.84, sources=2)]
        counts = queue.ingest(sample_entities, resolved)
        assert counts["pending"] == 1

    def test_import_merges_into_existing(self, queue, sample_entities, sample_resolved_pending, tmp_path):
        """Importing adds to existing candidates."""
        queue.ingest(sample_entities, sample_resolved_pending)
        assert len(queue) == 1

        out = tmp_path / "export.json"
        queue.export_decisions(str(out))

        # Import into same queue
        queue.import_decisions(str(out))
        # Should have 1 (overwritten, same ID) since import overwrites by ID
        assert len(queue) == 1
