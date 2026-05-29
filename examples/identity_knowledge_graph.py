#!/usr/bin/env python3
# Copyright 2026 unpatterned.ai — Apache 2.0
#
# Identity Knowledge Graph — How-To Example
# ===========================================
#
# Demonstrates arche-core's full pipeline: extract entities from text
# using GliNER (zero-shot NER model), match ISBN-10 to ISBN-13, group
# entities into identity clusters, build a NetworkX knowledge graph,
# and export an interactive vis.js visualisation.
#
# This example uses backend="auto" which runs the GliNER model for
# entity detection — the same model that powers arche in production.
# No manual entity creation. What the model finds, it finds. What it
# misses, we document honestly.
#
# Run:
#     cd <repo-root>
#     uv run python examples/identity_knowledge_graph.py
#
# Output:
#     examples/identity_graph.html   (open in any browser)
#     Console output showing each pipeline step
#
# Requirements:
#     pip install arche-core          (or: uv sync --all-packages)
#     No API keys. No GPU. No internet (after first model download).
#
# First run will download the GliNER model (~200MB). Subsequent runs
# use the cached model and start in <2 seconds.

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Step 0 — The source data
# ---------------------------------------------------------------------------
# Real book data: "Unscripted" by Dennis Irorere, published by Troubador
# Publishing. We structure the text to include the facts a knowledge graph
# should capture: author, publisher, ISBNs, and locations.
#
# The text is written as natural prose — no structured fields. GliNER must
# detect the entities from running text, just as it would on a real
# document, invoice, or catalogue entry.

TEXT = (
    "Dennis Irorere is a software engineer and author based in London. "
    "He wrote a book published by Troubador Publishing, a company "
    "headquartered in Leicester, United Kingdom. "
    "The book has ISBN 978-1-8063-4245-7 and is also listed under "
    "ISBN 1806342456."
)

print("=" * 72)
print("arche — Identity Knowledge Graph Example")
print("=" * 72)
print()
print("Source text:")
print(f"  {TEXT}")
print()


# ---------------------------------------------------------------------------
# Step 1 — Detect entities with GliNER (real NER model, no faking)
# ---------------------------------------------------------------------------
# backend="auto" tries GliNER first, then supplements with regex patterns
# for structured data (ISBNs, phones, national IDs) that regex handles
# better than statistical models.
#
# GliNER (urchade/gliner_multi_pii-v1) runs zero-shot NER: we give it
# identity-specific labels (person, organization, location, etc.) and it
# finds matching spans in the text. No training on our data required.
#
# What GliNER detects: PERSON, ORGANIZATION, LOCATION names.
# What regex detects: ISBNs (with checksum validation), phones, national IDs.
# The merge layer combines both, preferring validated regex for structured
# data and GliNER for fuzzy spans.

from arche.extract import extract

print("Step 1: Entity Detection (GliNER + regex via backend='auto')")
print("-" * 40)

t0 = time.perf_counter()
all_entities = extract(TEXT, backend="auto")
elapsed = time.perf_counter() - t0

print(f"  Model inference + regex: {elapsed:.2f}s")
print(f"  Entities detected: {len(all_entities)}")
print()

# Show what each backend found
gliner_entities = [e for e in all_entities if e.source == "gliner"]
regex_entities = [e for e in all_entities if e.source == "regex"]

print(f"  GliNER found {len(gliner_entities)} entities:")
for ent in gliner_entities:
    print(f"    [{ent.entity_type}] {ent.text!r}  "
          f"(confidence={ent.confidence:.0%})")

print(f"  Regex found {len(regex_entities)} entities:")
for ent in regex_entities:
    isbn_info = ""
    if ent.entity_type == "ISBN":
        isbn_info = f"  [{ent.metadata.get('isbn_type', '')}]"
    print(f"    [{ent.entity_type}] {ent.text!r}{isbn_info}  "
          f"(confidence={ent.confidence:.0%})")

print()

# --- Honest gap analysis ---
# Check what GliNER found vs what we know is in the text.
# This is how you evaluate a model: compare against known ground truth.
detected_texts = {e.text.lower() for e in all_entities}
expected = {
    "Dennis Irorere": "PERSON",
    "Troubador Publishing": "ORGANIZATION",
    "London": "LOCATION",
    "Leicester": "LOCATION",
    "United Kingdom": "LOCATION",
}

print("  Ground truth check:")
for name, expected_type in expected.items():
    found = any(
        name.lower() in e.text.lower() or e.text.lower() in name.lower()
        for e in all_entities
        if e.entity_type == expected_type
    )
    status = "DETECTED" if found else "MISSED (gap for fine-tuned model)"
    print(f"    {expected_type:15s} {name:25s} {status}")

isbn_count = sum(1 for e in all_entities if e.entity_type == "ISBN")
print(f"    {'ISBN':15s} {'(2 expected)':25s} {'DETECTED (' + str(isbn_count) + ')' if isbn_count >= 2 else 'PARTIAL (' + str(isbn_count) + ')'}")
print()

# Note: If GliNER misses entities (e.g., it may not detect "Troubador
# Publishing" as an organization, or may split "United Kingdom" oddly),
# that is a real gap. The fine-tuned arche-identity-ner model (planned
# for Q3-Q4 2026) will address these gaps with identity-specific training
# data. For now, what the model finds is what we show — no faking.


# ---------------------------------------------------------------------------
# Step 2 — Match ISBN-10 to ISBN-13 (cross-format matching)
# ---------------------------------------------------------------------------
# arche's Fellegi-Sunter matcher includes compare_isbns() which understands
# that ISBN-10 "1806342456" and ISBN-13 "9781806342457" refer to the same
# book (the 978 prefix + shared 9-digit core).

from arche.resolve._matcher import MatchScore, compare_isbns, match

# Find the ISBN entities
isbn_entities = [e for e in all_entities if e.entity_type == "ISBN"]

print("Step 2: ISBN Cross-Format Matching")
print("-" * 40)

if len(isbn_entities) >= 2:
    isbn_a = isbn_entities[0]
    isbn_b = isbn_entities[1]

    # Low-level comparison
    raw_sim = compare_isbns(isbn_a.text, isbn_b.text)
    print(f"  compare_isbns({isbn_a.text!r}, {isbn_b.text!r})")
    print(f"    Raw similarity: {raw_sim}")

    # High-level match() using Entity objects
    score: MatchScore = match(isbn_a, isbn_b)
    print(f"  match(Entity, Entity)")
    print(f"    Score:    {score.score:.4f}")
    print(f"    Decision: {score.decision}")
    print(f"    Factors:  {score.factors}")
    print(f"    Explanation: {score.explanation}")
    print()

    # Also demonstrate dict-based matching (Fellegi-Sunter record comparison)
    record_a = {"isbn": isbn_a.metadata.get("isbn_normalised", isbn_a.text)}
    record_b = {"isbn": isbn_b.metadata.get("isbn_normalised", isbn_b.text)}
    record_score = match(record_a, record_b)
    print(f"  Dict-based match: {record_score}")
else:
    print("  (fewer than 2 ISBNs detected — skipping match)")
print()


# ---------------------------------------------------------------------------
# Step 3 — Group by identity (entity relationships)
# ---------------------------------------------------------------------------
# group_by_identity() clusters entities that are near each other in the text
# into IdentityCluster objects.  Each cluster has an anchor (PERSON or ORG)
# and attributes (ISBN, LOCATION, PHONE, etc.) with typed relationships
# like AUTHORED, LOCATED_AT, HAS_ID.

from arche import group_by_identity

clusters = group_by_identity(all_entities, TEXT)

print("Step 3: Identity Clustering")
print("-" * 40)
for i, cluster in enumerate(clusters, 1):
    anchor_name = cluster.anchor.text if cluster.anchor else "<no anchor>"
    anchor_type = cluster.anchor.entity_type if cluster.anchor else "?"
    print(f"  Cluster {i}: {anchor_name} ({anchor_type})")
    for rel in cluster.relationships:
        print(f"    {rel.source.text} --[{rel.relation}]--> "
              f"{rel.target.text} ({rel.target.entity_type})  "
              f"conf={rel.confidence:.2f}")
    if not cluster.relationships and cluster.attributes:
        for attr in cluster.attributes:
            print(f"    (attribute) {attr.text} ({attr.entity_type})")
    print()


# ---------------------------------------------------------------------------
# Step 4 — Build a NetworkX knowledge graph
# ---------------------------------------------------------------------------
# build_graph() creates a NetworkX graph with entity nodes and relationship
# edges (CO_MENTIONED, SAME_AS, LOCATED_AT).  We also add custom edges from
# the identity clusters to capture AUTHORED and other semantic relationships.

from arche.graph import build_graph, export_graph

# Build the base graph (entity nodes + co-occurrence edges)
G = build_graph(all_entities)

# Enrich the graph with relationship edges from identity clustering.
# build_graph() only creates CO_MENTIONED and SAME_AS edges, so we add
# the richer relationship types (AUTHORED, HAS_ID, LOCATED_AT) manually.
node_map = {G.nodes[n]["label"]: n for n in G.nodes}

for cluster in clusters:
    for rel in cluster.relationships:
        src_node = node_map.get(rel.source.text)
        tgt_node = node_map.get(rel.target.text)
        if src_node and tgt_node:
            # Replace the generic CO_MENTIONED edge with the specific relation
            if G.has_edge(src_node, tgt_node):
                G.edges[src_node, tgt_node]["relation"] = rel.relation
                G.edges[src_node, tgt_node]["weight"] = rel.confidence
            else:
                G.add_edge(
                    src_node, tgt_node,
                    relation=rel.relation,
                    weight=rel.confidence,
                )

# Add a SAME_BOOK edge between the two ISBNs (they refer to the same book)
isbn_nodes = [n for n in G.nodes if G.nodes[n].get("entity_type") == "ISBN"]
if len(isbn_nodes) >= 2:
    G.add_edge(
        isbn_nodes[0], isbn_nodes[1],
        relation="SAME_BOOK",
        weight=1.0,
    )

print("Step 4: Knowledge Graph")
print("-" * 40)
print(f"  Nodes: {G.number_of_nodes()}")
print(f"  Edges: {G.number_of_edges()}")
print()

# Show all edges with their relationship types
print("  Edges:")
for u, v, data in G.edges(data=True):
    u_label = G.nodes[u]["label"]
    v_label = G.nodes[v]["label"]
    rel = data.get("relation", "UNKNOWN")
    weight = data.get("weight", 0)
    print(f"    {u_label} --[{rel}]--> {v_label}  (weight={weight:.2f})")
print()

# Export to JSON
graph_json = export_graph(G, format="json")
print(f"  JSON export: {len(graph_json)} chars")
print()


# ---------------------------------------------------------------------------
# Step 5 — Visualise the graph (interactive HTML with vis.js)
# ---------------------------------------------------------------------------
# We generate a standalone HTML file with vis.js that can be opened in any
# browser.  Nodes are color-coded by entity type.  Edges show relationship
# labels.  The graph is interactive: drag, zoom, hover for details.

# Color palette matching arche's design system
COLORS = {
    "PERSON": "#4f46e5",       # indigo
    "ORGANIZATION": "#0891b2", # cyan
    "LOCATION": "#059669",     # emerald
    "ISBN": "#d97706",         # amber
    "DATE": "#dc2626",         # red
}

# Node shapes by entity type
SHAPES = {
    "PERSON": "circle",
    "ORGANIZATION": "diamond",
    "LOCATION": "triangle",
    "ISBN": "box",
}

# Edge colors by relationship type
EDGE_COLORS = {
    "AUTHORED": "#4f46e5",
    "LOCATED_AT": "#059669",
    "SAME_BOOK": "#d97706",
    "CO_MENTIONED": "#e5e7eb",
    "HAS_ID": "#be185d",
}


def generate_graph_html(G, title: str = "arche Identity Knowledge Graph") -> str:
    """Generate a standalone vis.js HTML page from a NetworkX graph.

    Uses arche's Palantir-inspired design system: #101828 ink, #1a56db brand
    blue, #f9fafb background.
    """
    import json as _json

    nodes = []
    edges = []

    for node_id in G.nodes:
        data = G.nodes[node_id]
        etype = data.get("entity_type", "UNKNOWN")
        label = data.get("label", node_id)
        color = COLORS.get(etype, "#64748b")
        shape = SHAPES.get(etype, "box")

        # Build tooltip
        tooltip_parts = [f"Type: {etype}"]
        if data.get("confidence"):
            tooltip_parts.append(f"Confidence: {data['confidence']:.0%}")
        if data.get("source"):
            tooltip_parts.append(f"Source: {data['source']}")
        if data.get("isbn_type"):
            tooltip_parts.append(f"Format: {data['isbn_type']}")
        if data.get("isbn_normalised"):
            tooltip_parts.append(f"Normalised: {data['isbn_normalised']}")
        tooltip = "\n".join(tooltip_parts)

        nodes.append({
            "id": node_id,
            "label": label,
            "title": tooltip,
            "group": etype,
            "color": {"background": color + "30", "border": color},
            "font": {"color": "#101828", "size": 14, "face": "Inter, sans-serif"},
            "shape": shape,
            "size": 30 if etype == "PERSON" else 25,
            "borderWidth": 2,
        })

    for u, v, data in G.edges(data=True):
        rel = data.get("relation", "ASSOCIATED")
        weight = data.get("weight", 0.5)
        color = EDGE_COLORS.get(rel, "#94a3b8")

        edges.append({
            "from": u,
            "to": v,
            "label": rel,
            "title": f"{rel} (weight: {weight:.2f})",
            "color": {"color": color, "highlight": color},
            "width": max(1, int(weight * 3)),
            "font": {"size": 10, "color": "#667085", "align": "middle"},
            "smooth": {"type": "continuous"},
        })

    nodes_json = _json.dumps(nodes, indent=2)
    edges_json = _json.dumps(edges, indent=2)

    # Legend items
    legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:16px;">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{color};'
        f'display:inline-block;"></span>{etype}</span>'
        for etype, color in COLORS.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Inter, -apple-system, sans-serif; background: #f9fafb; color: #101828; }}

  .header {{
    background: #101828;
    color: white;
    padding: 1.25rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .header h1 {{
    font-family: 'DM Serif Display', Georgia, serif;
    font-size: 1.3rem;
    font-weight: 400;
  }}
  .header .badge {{
    background: #1a56db;
    color: white;
    padding: 0.25rem 0.75rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.05em;
  }}

  .toolbar {{
    background: white;
    border-bottom: 1px solid #e5e7eb;
    padding: 0.75rem 2rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
    font-size: 0.85rem;
    color: #667085;
  }}
  .stat {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }}
  .stat strong {{
    color: #101828;
    font-size: 1rem;
  }}
  .legend {{
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 0;
    font-size: 0.8rem;
    color: #344054;
  }}

  #graph {{
    width: 100%;
    height: calc(100vh - 110px);
  }}

  .footer {{
    position: fixed;
    bottom: 0;
    width: 100%;
    text-align: center;
    padding: 0.5rem;
    font-size: 0.7rem;
    color: #98a2b3;
    background: #f9fafb;
    border-top: 1px solid #f3f4f6;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>{title}</h1>
  <span class="badge">arche-core (GliNER)</span>
</div>

<div class="toolbar">
  <span class="stat"><strong>{G.number_of_nodes()}</strong> nodes</span>
  <span class="stat"><strong>{G.number_of_edges()}</strong> edges</span>
  <span class="stat"><strong>{len(clusters)}</strong> clusters</span>
  <span class="legend">{legend_items}</span>
</div>

<div id="graph"></div>

<div class="footer">
  Generated by arche v0.1.0a2 &mdash; unpatterned.ai &mdash;
  Entities detected by GliNER (urchade/gliner_multi_pii-v1) + regex validators.
  Drag nodes to rearrange. Scroll to zoom. Hover for details.
</div>

<script>
  var nodes = new vis.DataSet({nodes_json});
  var edges = new vis.DataSet({edges_json});

  var container = document.getElementById("graph");
  var data = {{ nodes: nodes, edges: edges }};
  var options = {{
    physics: {{
      solver: "forceAtlas2Based",
      forceAtlas2Based: {{
        gravitationalConstant: -40,
        centralGravity: 0.005,
        springLength: 200,
        springConstant: 0.04,
        damping: 0.4,
      }},
      stabilization: {{ iterations: 150 }},
    }},
    nodes: {{
      margin: 12,
      font: {{ size: 14 }},
      shadow: {{ enabled: true, size: 4, x: 2, y: 2, color: "rgba(0,0,0,0.1)" }},
    }},
    edges: {{
      smooth: {{ type: "continuous" }},
      arrows: {{ to: {{ enabled: true, scaleFactor: 0.6 }} }},
    }},
    interaction: {{
      hover: true,
      tooltipDelay: 100,
      zoomView: true,
      dragView: true,
    }},
  }};

  new vis.Network(container, data, options);
</script>
</body>
</html>"""


# Generate and save the HTML
html = generate_graph_html(G)
output_path = Path(__file__).parent / "identity_graph.html"
output_path.write_text(html, encoding="utf-8")

print("Step 5: Visualisation")
print("-" * 40)
print(f"  Interactive graph saved to: {output_path}")
print(f"  Open in a browser to explore the identity knowledge graph.")
print()


# ---------------------------------------------------------------------------
# Step 6 (removed in v0.2) — ISBN enrichment via Open Library
# ---------------------------------------------------------------------------
# Bibliographic enrichment (ISBN, Wikidata) was removed from arche in v0.2 as
# scope creep relative to the identity-workflow thesis (BP §2.1). If you need
# ISBN lookups, call the Open Library API directly:
#
#     import urllib.request, json
#     with urllib.request.urlopen(
#         "https://openlibrary.org/api/books?bibkeys=ISBN:9781806342457"
#         "&format=json&jscmd=data"
#     ) as r:
#         data = json.load(r)

print("=" * 72)
print("Done. Open examples/identity_graph.html in your browser.")
print()
print("Book data: 'Unscripted' by Dennis Irorere")
print("  ISBN-13: 9781806342457")
print("  ISBN-10: 1806342456")
print("  Publisher: Troubador Publishing")
print("=" * 72)
