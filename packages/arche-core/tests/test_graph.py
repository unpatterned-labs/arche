"""Tests for knowledge graph construction."""

import json

from arche.extract import Entity
from arche.graph import build_graph, export_graph
from arche.resolve import resolve_entities


def _entity(text, etype="PERSON", start=0, **meta):
    return Entity(text=text, entity_type=etype, confidence=0.9,
                  start=start, end=start + len(text), source="test", metadata=meta)


def test_build_graph_basic():
    entities = [_entity("Janet Okafor"), _entity("Lagos", "LOCATION", start=20)]
    G = build_graph(entities)
    assert G.number_of_nodes() == 2
    assert G.number_of_edges() >= 1


def test_build_graph_with_resolved():
    entities = [_entity("Janet Okafor"), _entity("Janet N. Okafor", start=30)]
    resolved = resolve_entities(entities, use_splink=False)
    G = build_graph(entities, resolved=resolved)
    same_as = [(u, v) for u, v, d in G.edges(data=True) if d.get("relation") == "SAME_AS"]
    assert len(same_as) >= 1


def test_build_graph_empty():
    G = build_graph([])
    assert G.number_of_nodes() == 0


def test_located_at_proximity_only():
    """LOCATED_AT edges should only exist for co-occurring entities."""
    entities = [
        _entity("Janet", start=0),
        _entity("Lagos", "LOCATION", start=10),   # near Janet
        _entity("David", start=500),
        _entity("Nairobi", "LOCATION", start=510),  # near David, far from Janet
    ]
    from arche.locate import Location
    locations = [
        Location(name="Lagos", country="NG", country_name="Nigeria",
                 region="Lagos", lat=6.5, lng=3.4, confidence=0.9),
        Location(name="Nairobi", country="KE", country_name="Kenya",
                 region="Nairobi", lat=-1.3, lng=36.8, confidence=0.9),
    ]
    G = build_graph(entities, locations=locations)
    # Janet should be linked to Lagos (within 200 chars)
    janet_lagos = G.has_edge("entity_0", "location_Lagos_NG")
    # David should be linked to Nairobi (within 200 chars)
    david_nairobi = G.has_edge("entity_2", "location_Nairobi_KE")
    # Janet should NOT be linked to Nairobi (500 chars apart)
    janet_nairobi = G.has_edge("entity_0", "location_Nairobi_KE")

    assert janet_lagos
    assert david_nairobi
    assert not janet_nairobi


def test_export_graph_json():
    entities = [_entity("Test Person")]
    G = build_graph(entities)
    output = export_graph(G, format="json")
    parsed = json.loads(output)
    assert "nodes" in parsed or "links" in parsed


def test_export_graph_invalid_format():
    import pytest
    G = build_graph([_entity("Test")])
    with pytest.raises(ValueError):
        export_graph(G, format="xml")
