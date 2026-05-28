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

"""Entity relationship extraction — link entities by context and proximity.

Given a list of extracted entities and the source text, groups them into
**identity clusters**: sets of entities that likely refer to the same
real-world identity based on their position in text.

"Fatima Abdullahi (NIN: 12345678901, phone +234 803 555 7890)"
→ one cluster: {PERSON: "Fatima Abdullahi", NATIONAL_ID: "12345678901", PHONE: "+234 803 555 7890"}

Usage::

    from arche import detect, extract_relationships, group_by_identity

    entities = detect("Fatima Abdullahi, NIN 12345678901. Kwame Mensah, phone +233 24 555 1234.")
    clusters = group_by_identity(entities, text)
    for cluster in clusters:
        print(cluster.anchor, "→", [e.text for e in cluster.attributes])
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..extract import Entity

# Entity types that can be an "anchor" — the primary identity
_ANCHOR_TYPES = {"PERSON", "ORGANIZATION"}

# Entity types that are "attributes" — belong to an anchor
_ATTRIBUTE_TYPES = {
    "PHONE", "NATIONAL_ID", "EMAIL", "DATE", "LOCATION",
    "ISBN", "MONEY",
}

# Relationship labels by attribute type
_RELATION_LABELS = {
    "PHONE": "HAS_PHONE",
    "NATIONAL_ID": "HAS_ID",
    "EMAIL": "HAS_EMAIL",
    "DATE": "HAS_DATE",
    "LOCATION": "LOCATED_AT",
    "ISBN": "AUTHORED",
    "MONEY": "HAS_AMOUNT",
    "ADDRESS": "LIVES_AT",
}


@dataclass
class EntityRelationship:
    """A directed relationship between two entities."""

    source: Entity
    target: Entity
    relation: str  # HAS_ID, HAS_PHONE, LOCATED_AT, AUTHORED, etc.
    confidence: float  # 0.0–1.0
    evidence: str  # why we think this relationship exists

    def __repr__(self) -> str:
        return (
            f"Relationship({self.source.text!r} —[{self.relation}]→ "
            f"{self.target.text!r}, conf={self.confidence:.2f})"
        )


@dataclass
class IdentityCluster:
    """A group of entities attributed to the same real-world identity.

    The ``anchor`` is the primary entity (usually a PERSON or ORGANIZATION).
    The ``attributes`` are entities that belong to it (phone, ID, address, etc.).
    """

    anchor: Entity | None  # PERSON or ORG — may be None if no anchor found
    attributes: list[Entity] = field(default_factory=list)
    relationships: list[EntityRelationship] = field(default_factory=list)

    @property
    def all_entities(self) -> list[Entity]:
        """All entities in this cluster (anchor + attributes)."""
        if self.anchor:
            return [self.anchor] + self.attributes
        return list(self.attributes)

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "anchor": {
                "text": self.anchor.text,
                "entity_type": self.anchor.entity_type,
            } if self.anchor else None,
            "attributes": [
                {
                    "text": e.text,
                    "entity_type": e.entity_type,
                    "relation": next(
                        (r.relation for r in self.relationships if r.target is e),
                        "ASSOCIATED",
                    ),
                }
                for e in self.attributes
            ],
        }

    def __repr__(self) -> str:
        anchor_text = self.anchor.text if self.anchor else "<no anchor>"
        return (
            f"IdentityCluster(anchor={anchor_text!r}, "
            f"attributes={len(self.attributes)})"
        )


def _sentence_boundaries(text: str) -> list[tuple[int, int]]:
    """Split text into approximate sentence spans.

    Returns a list of (start, end) character offsets.
    """
    boundaries: list[tuple[int, int]] = []
    # Split on sentence-ending punctuation followed by whitespace/newline
    pattern = re.compile(r'[.!?;]\s+|\n\s*\n|\n')
    prev = 0
    for m in pattern.finditer(text):
        end = m.end()
        if end - prev > 1:
            boundaries.append((prev, m.start()))
        prev = end
    if prev < len(text):
        boundaries.append((prev, len(text)))
    return boundaries


def _find_sentence(entity: Entity, sentences: list[tuple[int, int]]) -> int:
    """Find which sentence an entity belongs to. Returns sentence index."""
    mid = (entity.start + entity.end) // 2
    for i, (s, e) in enumerate(sentences):
        if s <= mid <= e:
            return i
    return -1


def group_by_identity(
    entities: list[Entity],
    text: str = "",
    *,
    proximity_chars: int = 150,
) -> list[IdentityCluster]:
    """Group entities into identity clusters based on text proximity.

    Entities near each other in text (same sentence or within
    ``proximity_chars``) are grouped together.  Each cluster gets an
    anchor (PERSON/ORG) and attributes (PHONE, ID, ADDRESS, etc.).

    Parameters
    ----------
    entities:
        Extracted entities (from :func:`arche.detect` or :func:`arche.extract`).
    text:
        Source text (used for sentence boundary detection). If empty,
        falls back to character proximity only.
    proximity_chars:
        Maximum character distance for entities to be grouped together
        when sentence detection isn't available.

    Returns
    -------
    list[IdentityCluster]
        Identity clusters with anchors and attributed entities.
    """
    if not entities:
        return []

    # Sort by position
    sorted_ents = sorted(entities, key=lambda e: (e.start, e.end))

    # Detect sentence boundaries
    sentences = _sentence_boundaries(text) if text else []

    # Assign each entity to a sentence (or use proximity-based grouping)
    if sentences:
        groups: dict[int, list[Entity]] = {}
        for ent in sorted_ents:
            sent_idx = _find_sentence(ent, sentences)
            groups.setdefault(sent_idx, []).append(ent)
    else:
        # Proximity-based grouping: entities within proximity_chars of
        # each other are in the same group
        groups = {}
        current_group = 0
        groups[0] = [sorted_ents[0]]
        for i in range(1, len(sorted_ents)):
            prev = sorted_ents[i - 1]
            curr = sorted_ents[i]
            if curr.start - prev.end > proximity_chars:
                current_group += 1
            groups.setdefault(current_group, []).append(curr)

    # Build clusters from groups
    clusters: list[IdentityCluster] = []
    for group_ents in groups.values():
        cluster = _build_cluster(group_ents)
        if cluster.anchor or cluster.attributes:
            clusters.append(cluster)

    return clusters


def _build_cluster(entities: list[Entity]) -> IdentityCluster:
    """Build an IdentityCluster from a group of co-occurring entities."""
    # Find anchor (PERSON or ORG — pick highest confidence)
    anchors = [e for e in entities if e.entity_type in _ANCHOR_TYPES]
    anchor = max(anchors, key=lambda e: e.confidence) if anchors else None

    # Remaining entities are attributes
    attributes = [e for e in entities if e is not anchor]

    # Build relationships
    relationships: list[EntityRelationship] = []
    if anchor:
        for attr in attributes:
            relation = _RELATION_LABELS.get(attr.entity_type, "ASSOCIATED_WITH")
            confidence = min(anchor.confidence, attr.confidence)

            # Boost confidence for very close entities
            dist = abs(attr.start - anchor.end)
            if dist < 30:
                confidence = min(confidence + 0.1, 1.0)

            relationships.append(
                EntityRelationship(
                    source=anchor,
                    target=attr,
                    relation=relation,
                    confidence=round(confidence, 4),
                    evidence=f"proximity:{dist}_chars",
                )
            )

    return IdentityCluster(
        anchor=anchor,
        attributes=attributes,
        relationships=relationships,
    )


def extract_relationships(
    entities: list[Entity],
    text: str = "",
) -> list[EntityRelationship]:
    """Extract all entity relationships from a set of entities.

    Convenience function that calls :func:`group_by_identity` and
    flattens all relationships.

    Parameters
    ----------
    entities:
        Extracted entities.
    text:
        Source text (for sentence-level grouping).

    Returns
    -------
    list[EntityRelationship]
        All entity relationships found.
    """
    clusters = group_by_identity(entities, text)
    relationships: list[EntityRelationship] = []
    for cluster in clusters:
        relationships.extend(cluster.relationships)
    return relationships
