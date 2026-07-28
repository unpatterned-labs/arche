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

"""C3-T3 / Lane F: legal citations survive resolution onto the resolved record."""

from arche.extract import Entity
from arche.resolve.classical import ResolvedEntity, resolve_entities
from arche.types import MatchDecision, resolved_to_identity_record


def _person(text: str, citation: str | None = None) -> Entity:
    meta = {"regulatory_citation": citation} if citation else {}
    return Entity(
        text=text, entity_type="PERSON", confidence=0.9, start=0, end=len(text),
        metadata=meta,
    )


def test_resolved_entity_derives_citation_from_mentions():
    re_ = ResolvedEntity(
        canonical_name="Fatima Abdullahi",
        entity_type="PERSON",
        aliases=[],
        confidence=0.95,
        sources=1,
        match_reasons=[],
        entities=[_person("Fatima Abdullahi", "NDPA-2023 s.30")],
    )
    assert re_.regulatory_citations == ["NDPA-2023 s.30"]


def test_citations_deduplicated_and_ordered():
    re_ = ResolvedEntity(
        canonical_name="Fatima Abdullahi",
        entity_type="PERSON",
        aliases=["Fatima A."],
        confidence=0.9,
        sources=3,
        match_reasons=[],
        entities=[
            _person("Fatima Abdullahi", "NDPA-2023 s.30"),
            _person("Fatima A.", "NIMC Act s.27"),
            _person("F. Abdullahi", "NDPA-2023 s.30"),  # duplicate citation
        ],
    )
    assert re_.regulatory_citations == ["NDPA-2023 s.30", "NIMC Act s.27"]


def test_no_citation_is_empty_not_crash():
    re_ = ResolvedEntity(
        canonical_name="John Doe",
        entity_type="PERSON",
        aliases=[],
        confidence=0.8,
        sources=1,
        match_reasons=[],
        entities=[_person("John Doe")],  # no citation metadata
    )
    assert re_.regulatory_citations == []


def test_explicit_citations_are_not_overwritten():
    re_ = ResolvedEntity(
        canonical_name="X",
        entity_type="PERSON",
        aliases=[],
        confidence=0.8,
        sources=1,
        match_reasons=[],
        entities=[_person("X", "NDPA-2023 s.30")],
        regulatory_citations=["POPIA s.19"],  # caller override
    )
    assert re_.regulatory_citations == ["POPIA s.19"]


def test_citation_survives_full_resolution_pipeline():
    entities = [
        _person("Fatima Abdullahi", "NDPA-2023 s.30"),
        _person("Fatima A.", "NDPA-2023 s.30"),
    ]
    resolved = resolve_entities(entities, use_splink=False)
    assert resolved, "expected at least one resolved entity"
    assert any("NDPA-2023 s.30" in r.regulatory_citations for r in resolved)


def test_citation_carries_onto_identity_record():
    re_ = ResolvedEntity(
        canonical_name="Fatima Abdullahi",
        entity_type="PERSON",
        aliases=[],
        confidence=0.95,
        sources=1,
        match_reasons=[],
        entities=[_person("Fatima Abdullahi", "NDPA-2023 s.30")],
    )
    record = resolved_to_identity_record(re_)
    assert record.regulatory_citations == ["NDPA-2023 s.30"]


def test_match_decision_carries_citation_fields():
    # Capability check: the audit-decision object can carry citations/version
    # (populated by the Pipeline→audit wiring, C3-T2).
    d = MatchDecision(
        cluster_id="c1",
        confidence=0.9,
        regulatory_citations=["NDPA-2023 s.30"],
        statute_id="NDPA-2023",
        statute_version="v1.0",
    )
    assert d.regulatory_citations == ["NDPA-2023 s.30"]
    assert d.statute_id == "NDPA-2023"
    assert d.statute_version == "v1.0"
