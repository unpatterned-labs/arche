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

"""Knowledge graph construction — build a NetworkX graph from extracted and resolved entities.

Usage:
    from arche.extract import extract
    from arche.resolve import resolve_entities
    from arche.graph import build_graph, export_graph

    entities = extract("Janet Okafor from Lagos met Kwame Mensah in Accra.")
    resolved = resolve_entities(entities)
    G = build_graph(entities, resolved=resolved)
    print(export_graph(G, format="json"))
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import networkx

    from ..extract import Entity
    from ..locate import Location
    from ..resolve import ResolvedEntity


# ===================================================================
# Public API
# ===================================================================


def build_graph(
    entities: list[Entity],
    resolved: list[ResolvedEntity] | None = None,
    locations: list[Location] | None = None,
) -> networkx.Graph:
    """Build a knowledge graph from entities and their relationships.

    Nodes represent entities; edges represent relationships such as co-occurrence,
    identity resolution (SAME_AS), and location association (LOCATED_AT).

    Parameters
    ----------
    entities:
        Raw extracted entities.
    resolved:
        Resolved/deduplicated entities (optional). Adds SAME_AS edges.
    locations:
        Geocoded locations (optional). Adds LOCATED_AT edges.

    Returns
    -------
    networkx.Graph
        An undirected graph with entity nodes and relationship edges.
    """
    import networkx as nx

    G = nx.Graph()

    # --- 1. Add entity nodes ---
    for i, ent in enumerate(entities):
        node_id = f"entity_{i}"
        G.add_node(
            node_id,
            label=ent.text,
            entity_type=ent.entity_type,
            confidence=ent.confidence,
            source=ent.source,
            start=ent.start,
            end=ent.end,
            node_kind="entity",
            **{k: str(v) for k, v in ent.metadata.items()},
        )

    # --- 2. Add co-occurrence edges (all entities co-mentioned in the same text) ---
    entity_node_ids = [f"entity_{i}" for i in range(len(entities))]
    for i in range(len(entity_node_ids)):
        for j in range(i + 1, len(entity_node_ids)):
            ni, nj = entity_node_ids[i], entity_node_ids[j]
            # Only add co-occurrence if entities are of different types or different texts
            ent_i, ent_j = entities[i], entities[j]
            if ent_i.text != ent_j.text or ent_i.entity_type != ent_j.entity_type:
                G.add_edge(
                    ni,
                    nj,
                    relation="CO_MENTIONED",
                    weight=0.5,
                )

    # --- 3. Add resolution edges (SAME_AS) ---
    if resolved:
        _entity_to_node = _build_entity_index(entities, entity_node_ids)
        for res in resolved:
            if res.sources > 1 and len(res.entities) > 1:
                # Add a canonical node
                canonical_id = f"resolved_{res.canonical_name}"
                G.add_node(
                    canonical_id,
                    label=res.canonical_name,
                    entity_type=res.entity_type,
                    confidence=res.confidence,
                    sources=res.sources,
                    aliases=", ".join(res.aliases),
                    node_kind="resolved",
                )
                # Link each member entity to the canonical node
                for member_ent in res.entities:
                    member_node = _entity_to_node.get(id(member_ent))
                    if member_node and G.has_node(member_node):
                        G.add_edge(
                            member_node,
                            canonical_id,
                            relation="SAME_AS",
                            confidence=res.confidence,
                            weight=res.confidence,
                        )

    # --- 4. Add location edges (LOCATED_AT) ---
    if locations:
        for loc in locations:
            loc_id = f"location_{loc.name}_{loc.country}"
            if not G.has_node(loc_id):
                G.add_node(
                    loc_id,
                    label=loc.name,
                    entity_type="LOCATION",
                    country=loc.country,
                    country_name=loc.country_name,
                    region=loc.region,
                    lat=loc.lat,
                    lng=loc.lng,
                    confidence=loc.confidence,
                    node_kind="location",
                )

            # Link person/org entities to locations — only when co-occurring
            # (within 200 chars in source text, or same patient_id in FHIR)
            for j, loc_ent in enumerate(entities):
                if loc_ent.entity_type != "LOCATION" or loc_ent.text != loc.name:
                    continue
                for i, ent in enumerate(entities):
                    if ent.entity_type not in ("PERSON", "ORGANIZATION"):
                        continue
                    # Proximity check: within 200 chars in source text
                    near_in_text = abs(ent.start - loc_ent.start) <= 200
                    # Metadata check: same patient_id (FHIR data)
                    ent_pid = ent.metadata.get("patient_id", "")
                    loc_pid = loc_ent.metadata.get("patient_id", "")
                    same_patient = ent_pid and ent_pid == loc_pid

                    if near_in_text or same_patient:
                        G.add_edge(
                            f"entity_{i}",
                            loc_id,
                            relation="LOCATED_AT",
                            weight=loc.confidence * 0.5,
                        )

    return G


def export_graph(graph: networkx.Graph, format: str = "json") -> str:
    """Export a knowledge graph to a serialisable format.

    Parameters
    ----------
    graph:
        A NetworkX graph built by :func:`build_graph`.
    format:
        ``"json"`` — node-link JSON (default).
        ``"graphml"`` — GraphML XML.
        ``"gexf"`` — GEXF XML.

    Returns
    -------
    str
        The serialised graph as a string.
    """
    import networkx as nx

    if format == "json":
        data = nx.node_link_data(graph)
        return json.dumps(data, indent=2, default=str)
    elif format == "graphml":
        from io import BytesIO

        buf = BytesIO()
        nx.write_graphml(graph, buf)
        return buf.getvalue().decode("utf-8")
    elif format == "gexf":
        from io import BytesIO

        buf = BytesIO()
        nx.write_gexf(graph, buf)
        return buf.getvalue().decode("utf-8")
    else:
        raise ValueError(
            f"Unknown export format: {format!r}. Use 'json', 'graphml', or 'gexf'."
        )


# ===================================================================
# Helpers
# ===================================================================


def _build_entity_index(
    entities: list[Entity],
    node_ids: list[str],
) -> dict:
    """Build a mapping from entity object id to graph node id."""
    return {id(ent): nid for ent, nid in zip(entities, node_ids)}
