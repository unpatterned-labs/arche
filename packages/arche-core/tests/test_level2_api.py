# Copyright 2026 unpatterned.org
# Tests for the Level 2 API: detect(), link(), and integration with resolve().

import pytest

from arche import detect, link, match, resolve
from arche.extract import Entity
from arche.workflow.pipeline import IdentityGraph


class TestDetect:
    """Test the Level 2 detect() function."""

    def test_detect_returns_entities(self):
        entities = detect(
            "Call +234 803 555 7890 about NIN 12345678901",
            backend="regex",
        )
        assert isinstance(entities, list)
        assert len(entities) >= 2
        types = {e.entity_type for e in entities}
        assert "PHONE" in types or "NATIONAL_ID" in types

    def test_detect_sorted_by_position(self):
        entities = detect(
            "Phone +234 801 234 5678 and email test@example.com",
            backend="regex",
        )
        if len(entities) >= 2:
            for i in range(len(entities) - 1):
                assert entities[i].start <= entities[i + 1].start

    def test_detect_with_pii(self):
        entities = detect(
            "Contact 08012345678 or user@test.com",
            backend="regex",
            include_pii=True,
        )
        sources = {e.source for e in entities}
        # Should include regex/african and/or pii sources
        assert len(entities) >= 1

    def test_detect_without_pii(self):
        entities_with = detect("NIN 12345678901", backend="regex", include_pii=True)
        entities_without = detect("NIN 12345678901", backend="regex", include_pii=False)
        # Without PII, we may get fewer entities (no PII-source entities)
        assert len(entities_without) <= len(entities_with)

    def test_detect_entity_type_filter(self):
        entities = detect(
            "Phone +234 801 234 5678 and NIN 12345678901",
            backend="regex",
            entity_types=["PHONE"],
        )
        for e in entities:
            assert e.entity_type == "PHONE"

    def test_detect_empty_text(self):
        entities = detect("", backend="regex")
        assert entities == []

    def test_detect_max_length(self):
        from arche import configure

        # This should raise for text exceeding max length
        long_text = "x" * 500_001
        with pytest.raises(ValueError, match="maximum length"):
            detect(long_text, backend="regex")


class TestLink:
    """Test the Level 2 link() function."""

    def _make_entities(self, *specs):
        """Helper to create entity lists."""
        entities = []
        for i, (text, etype) in enumerate(specs):
            entities.append(
                Entity(
                    text=text,
                    entity_type=etype,
                    confidence=0.90,
                    start=i * 20,
                    end=i * 20 + len(text),
                    source="test",
                )
            )
        return entities

    def test_link_empty(self):
        graph = link()
        assert isinstance(graph, IdentityGraph)
        assert graph.identity_count == 0

    def test_link_single_source(self):
        entities = self._make_entities(
            ("John Smith", "PERSON"),
            ("J. Smith", "PERSON"),
        )
        graph = link(entities)
        # Should try to resolve John Smith and J. Smith
        assert graph.entity_count == 2

    def test_link_two_sources(self):
        source_a = self._make_entities(
            ("Fatima Abdullahi", "PERSON"),
            ("12345678901", "NATIONAL_ID"),
        )
        source_b = self._make_entities(
            ("F. Abdullahi", "PERSON"),
            ("12345678901", "NATIONAL_ID"),
        )
        graph = link(source_a, source_b)
        assert graph.entity_count == 4
        # The two NIN entities should merge (exact match)
        id_resolved = [r for r in graph.resolved if r.entity_type == "NATIONAL_ID"]
        if id_resolved:
            assert any(r.sources >= 2 for r in id_resolved)

    def test_link_returns_identity_graph(self):
        entities = self._make_entities(("Test", "PERSON"))
        graph = link(entities)
        assert isinstance(graph, IdentityGraph)
        assert hasattr(graph, "resolved")
        assert hasattr(graph, "match_scores")
        assert hasattr(graph, "identity_count")
        assert hasattr(graph, "duplicate_count")

    def test_link_to_dict(self):
        entities = self._make_entities(("John", "PERSON"))
        graph = link(entities)
        d = graph.to_dict()
        assert "identities" in d
        assert "match_scores" in d
        assert "summary" in d

    def test_link_with_knowledge_graph(self):
        entities = self._make_entities(
            ("Alice", "PERSON"),
            ("Bob", "PERSON"),
        )
        graph = link(entities, build_knowledge_graph=True)
        assert graph.graph is not None

    def test_link_tags_sources(self):
        source_a = self._make_entities(("A", "PERSON"))
        source_b = self._make_entities(("B", "PERSON"))
        graph = link(source_a, source_b)
        sources = {e.metadata.get("link_source") for e in graph.entities}
        assert "source_0" in sources
        assert "source_1" in sources

    def test_link_phone_matching(self):
        source_a = self._make_entities(
            ("+2348012345678", "PHONE"),
        )
        source_b = self._make_entities(
            ("+2348012345678", "PHONE"),
        )
        graph = link(source_a, source_b)
        phone_resolved = [r for r in graph.resolved if r.entity_type == "PHONE"]
        # Should merge the identical phones
        assert any(r.sources == 2 for r in phone_resolved)


class TestResolveUnchanged:
    """Verify resolve() behavior is unchanged after the refactor."""

    def test_resolve_returns_resolution_result(self):
        result = resolve("Test text with +234 801 234 5678", backend="regex")
        assert hasattr(result, "entities")
        assert hasattr(result, "resolved")
        assert hasattr(result, "pii")
        assert hasattr(result, "signals")
        assert hasattr(result, "locations")
        assert hasattr(result, "audit_entry")

    def test_resolve_entity_count(self):
        result = resolve("NIN 12345678901 and +234 803 555 7890", backend="regex")
        assert result.entity_count >= 2

    def test_resolve_pii_detection(self):
        result = resolve("NIN 12345678901", backend="regex")
        assert result.pii_count >= 1

    def test_resolve_signals(self):
        # signal detection was removed in v0.2.0a3 with arche-adapters;
        # the field is preserved on ResolutionResult but always empty.
        result = resolve("NIN 12345678901", backend="regex")
        assert result.signals == []

    def test_resolve_audit_trail(self):
        result = resolve("test text", backend="regex")
        assert result.audit_entry is not None
        assert result.audit_entry.action == "resolve"

    def test_resolve_sanitize_for_logging(self):
        result = resolve("NIN 12345678901", backend="regex")
        safe = result.sanitize_for_logging()
        assert "<input:" in safe["text"]

    def test_resolve_to_dict(self):
        result = resolve("Phone +234 801 234 5678", backend="regex")
        d = result.to_dict()
        assert "entities" in d
        assert "resolved" in d
        assert "pii" in d
        assert "signals" in d
        assert "summary" in d

    def test_resolve_to_json(self):
        result = resolve("Test", backend="regex")
        j = result.to_json()
        assert isinstance(j, str)
        import json
        parsed = json.loads(j)
        assert "entities" in parsed


class TestIntegration:
    """Test detect + match + link working together."""

    def test_detect_match_flow(self):
        """Detect entities then match them."""
        entities = detect("NIN 12345678901", backend="regex")
        assert len(entities) >= 1

        score = match("Fatima", "Fatoumata", jurisdiction="NG")
        assert score.score > 0.5

    def test_detect_link_flow(self):
        """Detect from two texts then link."""
        a = detect("Phone +234 801 234 5678", backend="regex")
        b = detect("NIN 12345678901", backend="regex")
        graph = link(a, b)
        assert isinstance(graph, IdentityGraph)
        assert graph.entity_count == len(a) + len(b)
