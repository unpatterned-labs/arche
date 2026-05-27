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

"""Human review queue for identity resolution match candidates.

Real Master Patient Index (MPI) systems need a middle ground between
auto-accepted matches and auto-rejected non-matches. Matches with
confidence between two thresholds go to a review queue where a human
operator (or an AI agent via MCP) makes the final decision.

Usage::

    from arche import ReviewQueue
    queue = ReviewQueue(auto_accept=0.85, auto_reject=0.30)
    queue.ingest(entities, resolved)

    for candidate in queue.pending():
        print(candidate.record_a, candidate.record_b, candidate.confidence)

    queue.approve(candidate.id, reviewer="human_1", notes="Same person")
    queue.export_decisions("reviews.json")
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ..extract import Entity
from ..resolve import ResolvedEntity

_log = logging.getLogger("arche")

# Valid statuses for a review candidate
ReviewStatus = Literal["pending", "approved", "rejected", "escalated", "auto_approved", "auto_rejected"]


@dataclass
class ReviewCandidate:
    """A potential identity match awaiting human or agent review.

    Attributes
    ----------
    id:
        Unique identifier (UUID4) for this review candidate.
    record_a:
        First record in the potential match pair.
    record_b:
        Second record in the potential match pair.
    confidence:
        Match probability from the resolution engine (0.0 -- 1.0).
    match_reasons:
        Why the system thinks these records match (e.g. name similarity,
        phone match, national ID match).
    status:
        Current status: ``pending``, ``approved``, ``rejected``,
        ``escalated``, ``auto_approved``, or ``auto_rejected``.
    reviewer:
        Identifier of who reviewed this candidate (human or agent).
    reviewed_at:
        ISO 8601 timestamp of when the review decision was made.
    notes:
        Free-text notes from the reviewer explaining the decision.
    created_at:
        ISO 8601 timestamp of when the candidate was created.
    """

    id: str
    record_a: dict
    record_b: dict
    confidence: float
    match_reasons: list[str]
    status: str = "pending"
    reviewer: str = ""
    reviewed_at: str = ""
    notes: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return asdict(self)

    def __repr__(self) -> str:
        name_a = self.record_a.get("canonical_name", "?")
        name_b = self.record_b.get("canonical_name", "?")
        return (
            f"ReviewCandidate(id={self.id!r}, "
            f"a={name_a!r}, b={name_b!r}, "
            f"confidence={self.confidence:.2f}, status={self.status!r})"
        )


def _entity_to_record(entity: Entity) -> dict:
    """Convert an Entity to a plain dict for review storage."""
    return {
        "text": entity.text,
        "entity_type": entity.entity_type,
        "confidence": entity.confidence,
        "start": entity.start,
        "end": entity.end,
        "source": entity.source,
        "metadata": dict(entity.metadata) if entity.metadata else {},
    }


def _resolved_to_record(resolved: ResolvedEntity) -> dict:
    """Convert a ResolvedEntity to a plain dict for review storage."""
    return {
        "canonical_name": resolved.canonical_name,
        "entity_type": resolved.entity_type,
        "aliases": list(resolved.aliases),
        "confidence": resolved.confidence,
        "sources": resolved.sources,
        "match_reasons": list(resolved.match_reasons),
    }


class ReviewQueue:
    """In-memory review queue for identity match candidates.

    Matches above ``auto_accept`` are automatically approved.
    Matches below ``auto_reject`` are automatically rejected.
    Everything in between goes to the pending review queue.

    Usage::

        queue = ReviewQueue(auto_accept=0.85, auto_reject=0.30)
        queue.ingest(entities, resolved)

        for candidate in queue.pending():
            print(candidate.record_a, candidate.record_b, candidate.confidence)

        queue.approve(candidate.id, reviewer="human_1", notes="Same person")

    Parameters
    ----------
    auto_accept:
        Confidence threshold above which matches are automatically
        approved (default 0.85).
    auto_reject:
        Confidence threshold below which matches are automatically
        rejected (default 0.30).
    persistence_path:
        Optional path to a JSON file for persisting the queue. If
        provided, the queue is loaded on init and saved on every
        mutation.
    """

    def __init__(
        self,
        auto_accept: float = 0.85,
        auto_reject: float = 0.30,
        persistence_path: str | Path | None = None,
    ) -> None:
        if auto_reject >= auto_accept:
            raise ValueError(
                f"auto_reject ({auto_reject}) must be less than "
                f"auto_accept ({auto_accept})"
            )
        if not (0.0 <= auto_reject <= 1.0) or not (0.0 <= auto_accept <= 1.0):
            raise ValueError(
                "Thresholds must be between 0.0 and 1.0. "
                f"Got auto_accept={auto_accept}, auto_reject={auto_reject}"
            )

        self.auto_accept = auto_accept
        self.auto_reject = auto_reject
        self._candidates: dict[str, ReviewCandidate] = {}
        self._persistence_path: Path | None = (
            Path(persistence_path) if persistence_path else None
        )

        # Load existing state if persistence file exists
        if self._persistence_path and self._persistence_path.exists():
            self._load()

    # =================================================================
    # Ingestion
    # =================================================================

    def ingest(
        self,
        entities: list[Entity],
        resolved: list[ResolvedEntity],
    ) -> dict[str, int]:
        """Ingest resolved entities and route them by confidence.

        ResolvedEntities with ``sources > 1`` (i.e. merged clusters) are
        treated as match pairs. Their confidence determines routing:

        - **Above auto_accept** -> ``auto_approved``
        - **Below auto_reject** -> ``auto_rejected``
        - **In between** -> ``pending`` (human review required)

        Parameters
        ----------
        entities:
            Raw entities from :func:`arche.extract.extract`.
        resolved:
            Resolved entities from :func:`arche.resolve.resolve_entities`.

        Returns
        -------
        dict[str, int]
            Counts of candidates routed: ``{"auto_approved": N,
            "auto_rejected": N, "pending": N}``.
        """
        counts = {"auto_approved": 0, "auto_rejected": 0, "pending": 0}

        for re_ent in resolved:
            # Only consider merged clusters (multiple mentions resolved together)
            if re_ent.sources <= 1:
                continue

            # Build record pair from the cluster's member entities.
            # We pair the first entity with each subsequent entity in the
            # cluster. For a cluster of N entities, this produces N-1
            # review candidates.
            member_entities = re_ent.entities
            if len(member_entities) < 2:
                continue

            confidence = re_ent.confidence

            # Generate pairwise candidates from the cluster
            for i in range(1, len(member_entities)):
                record_a = _entity_to_record(member_entities[0])
                record_b = _entity_to_record(member_entities[i])

                candidate_id = str(uuid.uuid4())

                if confidence >= self.auto_accept:
                    status: str = "auto_approved"
                    counts["auto_approved"] += 1
                elif confidence <= self.auto_reject:
                    status = "auto_rejected"
                    counts["auto_rejected"] += 1
                else:
                    status = "pending"
                    counts["pending"] += 1

                candidate = ReviewCandidate(
                    id=candidate_id,
                    record_a=record_a,
                    record_b=record_b,
                    confidence=confidence,
                    match_reasons=list(re_ent.match_reasons),
                    status=status,
                )
                self._candidates[candidate_id] = candidate

        _log.info(
            "ReviewQueue ingested: %d auto_approved, %d auto_rejected, %d pending",
            counts["auto_approved"],
            counts["auto_rejected"],
            counts["pending"],
        )

        self._save()
        return counts

    # =================================================================
    # Query
    # =================================================================

    def pending(self) -> list[ReviewCandidate]:
        """Return pending candidates sorted by confidence (highest first).

        Returns
        -------
        list[ReviewCandidate]
            Candidates awaiting review, highest confidence first.
        """
        return sorted(
            [c for c in self._candidates.values() if c.status == "pending"],
            key=lambda c: c.confidence,
            reverse=True,
        )

    def get(self, candidate_id: str) -> ReviewCandidate:
        """Get a specific candidate by ID.

        Parameters
        ----------
        candidate_id:
            UUID of the candidate.

        Returns
        -------
        ReviewCandidate

        Raises
        ------
        KeyError
            If the candidate ID is not found.
        """
        if candidate_id not in self._candidates:
            raise KeyError(f"Review candidate not found: {candidate_id!r}")
        return self._candidates[candidate_id]

    def all(self) -> list[ReviewCandidate]:
        """Return all candidates regardless of status.

        Returns
        -------
        list[ReviewCandidate]
            All candidates sorted by creation time (newest first).
        """
        return sorted(
            self._candidates.values(),
            key=lambda c: c.created_at,
            reverse=True,
        )

    # =================================================================
    # Review actions
    # =================================================================

    def _review(
        self,
        candidate_id: str,
        status: str,
        reviewer: str = "",
        notes: str = "",
    ) -> ReviewCandidate:
        """Internal: apply a review decision to a candidate."""
        candidate = self.get(candidate_id)
        if candidate.status not in ("pending", "escalated"):
            raise ValueError(
                f"Cannot review candidate {candidate_id!r}: "
                f"status is {candidate.status!r} (must be 'pending' or 'escalated')"
            )
        candidate.status = status
        candidate.reviewer = reviewer
        candidate.reviewed_at = datetime.now(timezone.utc).isoformat()
        candidate.notes = notes
        self._save()
        return candidate

    def approve(
        self,
        candidate_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> ReviewCandidate:
        """Approve a match candidate.

        Parameters
        ----------
        candidate_id:
            UUID of the candidate to approve.
        reviewer:
            Identifier of who is approving (human name, agent ID, etc.).
        notes:
            Free-text explanation for the decision.

        Returns
        -------
        ReviewCandidate
            The updated candidate.
        """
        return self._review(candidate_id, "approved", reviewer, notes)

    def reject(
        self,
        candidate_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> ReviewCandidate:
        """Reject a match candidate.

        Parameters
        ----------
        candidate_id:
            UUID of the candidate to reject.
        reviewer:
            Identifier of who is rejecting.
        notes:
            Free-text explanation for the decision.

        Returns
        -------
        ReviewCandidate
            The updated candidate.
        """
        return self._review(candidate_id, "rejected", reviewer, notes)

    def escalate(
        self,
        candidate_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> ReviewCandidate:
        """Escalate a candidate for further review.

        Use this when the reviewer is uncertain and needs a more senior
        human or a different process to decide.

        Parameters
        ----------
        candidate_id:
            UUID of the candidate to escalate.
        reviewer:
            Identifier of who is escalating.
        notes:
            Free-text explanation for the escalation.

        Returns
        -------
        ReviewCandidate
            The updated candidate.
        """
        candidate = self.get(candidate_id)
        if candidate.status != "pending":
            raise ValueError(
                f"Cannot escalate candidate {candidate_id!r}: "
                f"status is {candidate.status!r} (must be 'pending')"
            )
        candidate.status = "escalated"
        candidate.reviewer = reviewer
        candidate.reviewed_at = datetime.now(timezone.utc).isoformat()
        candidate.notes = notes
        self._save()
        return candidate

    # =================================================================
    # Statistics
    # =================================================================

    def stats(self) -> dict[str, int]:
        """Return counts of candidates by status.

        Returns
        -------
        dict[str, int]
            Keys: ``total``, ``pending``, ``approved``, ``rejected``,
            ``escalated``, ``auto_approved``, ``auto_rejected``.
        """
        counts: dict[str, int] = {
            "total": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "escalated": 0,
            "auto_approved": 0,
            "auto_rejected": 0,
        }
        for c in self._candidates.values():
            counts["total"] += 1
            if c.status in counts:
                counts[c.status] += 1
        return counts

    # =================================================================
    # Persistence (JSON)
    # =================================================================

    def export_decisions(self, path: str | Path) -> int:
        """Export all decisions to a JSON file (audit trail).

        Parameters
        ----------
        path:
            Output file path.

        Returns
        -------
        int
            Number of candidates exported.
        """
        data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "auto_accept": self.auto_accept,
            "auto_reject": self.auto_reject,
            "stats": self.stats(),
            "candidates": [c.to_dict() for c in self.all()],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        _log.info("Exported %d review decisions to %s", len(self._candidates), path)
        return len(self._candidates)

    def import_decisions(self, path: str | Path) -> int:
        """Import decisions from a JSON file.

        Previously exported decisions are merged into the current queue.
        Existing candidates with the same ID are overwritten.

        Parameters
        ----------
        path:
            Input file path (from :meth:`export_decisions`).

        Returns
        -------
        int
            Number of candidates imported.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Review decisions file not found: {path}")

        with open(p, encoding="utf-8") as f:
            data = json.load(f)

        candidates = data.get("candidates", [])
        count = 0
        for raw in candidates:
            candidate = ReviewCandidate(
                id=raw["id"],
                record_a=raw["record_a"],
                record_b=raw["record_b"],
                confidence=raw["confidence"],
                match_reasons=raw.get("match_reasons", []),
                status=raw.get("status", "pending"),
                reviewer=raw.get("reviewer", ""),
                reviewed_at=raw.get("reviewed_at", ""),
                notes=raw.get("notes", ""),
                created_at=raw.get("created_at", ""),
            )
            self._candidates[candidate.id] = candidate
            count += 1

        _log.info("Imported %d review decisions from %s", count, path)
        self._save()
        return count

    def _save(self) -> None:
        """Persist queue to disk if a persistence_path is configured."""
        if self._persistence_path is None:
            return
        data = {
            "auto_accept": self.auto_accept,
            "auto_reject": self.auto_reject,
            "candidates": [c.to_dict() for c in self._candidates.values()],
        }
        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persistence_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _load(self) -> None:
        """Load queue from disk."""
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        with open(self._persistence_path, encoding="utf-8") as f:
            data = json.load(f)
        for raw in data.get("candidates", []):
            candidate = ReviewCandidate(
                id=raw["id"],
                record_a=raw["record_a"],
                record_b=raw["record_b"],
                confidence=raw["confidence"],
                match_reasons=raw.get("match_reasons", []),
                status=raw.get("status", "pending"),
                reviewer=raw.get("reviewer", ""),
                reviewed_at=raw.get("reviewed_at", ""),
                notes=raw.get("notes", ""),
                created_at=raw.get("created_at", ""),
            )
            self._candidates[candidate.id] = candidate

    def clear(self) -> None:
        """Remove all candidates from the queue."""
        self._candidates.clear()
        self._save()

    def __len__(self) -> int:
        return len(self._candidates)

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"ReviewQueue(total={s['total']}, pending={s['pending']}, "
            f"auto_accept={self.auto_accept}, auto_reject={self.auto_reject})"
        )
