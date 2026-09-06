#!/usr/bin/env python3
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Identity knowledge graph -- from one paragraph to an interactive graph.

Extract entities from prose with GliNER plus the regex validators, match the
ISBN-10 to the ISBN-13, group what was found around the people and
organisations it belongs to, build a NetworkX graph, and write a standalone
vis.js page you can open in a browser.

Run:

    uv run --no-sync python examples/identity_knowledge_graph.py

Output:

    examples/identity_graph.html   (open in any browser)
    console output for each step

``backend="auto"`` uses the GliNER model when ``arche-core[detect]`` is
installed (first run downloads ~200 MB; later runs start in seconds) and falls
back to the regex extractor otherwise. What the model finds is what is shown:
the ground-truth check below prints the gaps rather than papering over them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import arche
import networkx as nx
from arche.extract import Entity, extract
from arche.resolve._matcher import compare_isbns, match

# ---------------------------------------------------------------------------
# Step 0 -- the source data
# ---------------------------------------------------------------------------
# Real book data, written as natural prose: no structured fields. The extractor
# has to find the author, the publisher, the places and both ISBNs from text,
# just as it would on an invoice, a catalogue entry or a news article.
TEXT = (
    "Dennis Irorere is a software engineer and author based in London. "
    "He wrote a book published by Troubador Publishing, a company "
    "headquartered in Leicester, United Kingdom. "
    "The book has ISBN 978-1-8063-4245-7 and is also listed under "
    "ISBN 1806342456."
)

print("=" * 72)
print("arche -- identity knowledge graph")
print("=" * 72)
print()
print("Source text:")
print(f"  {TEXT}")
print()

# ---------------------------------------------------------------------------
# Step 1 -- detect entities
# ---------------------------------------------------------------------------
# backend="auto": GliNER for the fuzzy spans (people, organisations, places),
# regex with checksum validation for the structured ones (ISBNs, phones,
# national ids). The merge prefers the validated regex span where both fire.
print("Step 1: entity detection (backend='auto')")
print("-" * 40)
t0 = time.perf_counter()
entities = extract(TEXT, backend="auto")
print(f"  {len(entities)} entities in {time.perf_counter() - t0:.2f}s")
for source in sorted({e.source for e in entities}):
    found = [e for e in entities if e.source == source]
    print(f"  {source} found {len(found)}:")
    for e in found:
        extra = f"  [{e.metadata.get('isbn_type', '')}]" if e.entity_type == "ISBN" else ""
        print(f"    [{e.entity_type}] {e.text!r}{extra}  (confidence={e.confidence:.0%})")
print()

# Ground-truth check: this is how a model is evaluated -- against what is
# known to be in the text, printed whichever way it falls.
EXPECTED = {
    "Dennis Irorere": "PERSON",
    "Troubador Publishing": "ORGANIZATION",
    "London": "LOCATION",
    "Leicester": "LOCATION",
    "United Kingdom": "LOCATION",
}
print("  Ground truth:")
for name, kind in EXPECTED.items():
    hit = any(kind == e.entity_type
              and (name.lower() in e.text.lower() or e.text.lower() in name.lower())
              for e in entities)
    print(f"    {kind:13s} {name:22s} {'DETECTED' if hit else 'MISSED'}")
isbns = sorted((e for e in entities if e.entity_type == "ISBN"), key=lambda e: e.start)
isbn_status = "DETECTED" if len(isbns) >= 2 else "PARTIAL"
print(f"    {'ISBN':13s} {'(2 expected)':22s} {isbn_status} ({len(isbns)})")
print()

# ---------------------------------------------------------------------------
# Step 2 -- ISBN-10 against ISBN-13
# ---------------------------------------------------------------------------
# The matcher knows that "1806342456" and "9781806342457" name the same book:
# the 978 prefix plus the shared nine-digit core, each with its own checksum.
print("Step 2: ISBN cross-format matching")
print("-" * 40)
if len(isbns) >= 2:
    a, b = isbns[0], isbns[1]
    print(f"  compare_isbns({a.text!r}, {b.text!r}) = {compare_isbns(a.text, b.text)}")
    score = match(a, b)
    print(f"  match(Entity, Entity): score={score.score:.4f} decision={score.decision}")
    print(f"    factors: {score.factors}")
    print(f"    {score.explanation}")
else:
    print("  fewer than two ISBNs detected -- skipping")
print()

# ---------------------------------------------------------------------------
# Step 3 -- group what was found around who it belongs to
# ---------------------------------------------------------------------------
# A person or an organisation anchors a cluster; every other entity joins the
# nearest anchor that precedes it in the text, or the nearest one after it if
# nothing precedes. The relation is read off the pair of types. This is text
# proximity, not resolution: it says what the paragraph put next to what.
ANCHORS = {"PERSON", "ORGANIZATION"}
RELATION = {
    ("PERSON", "ORGANIZATION"): "AFFILIATED_WITH",
    ("PERSON", "LOCATION"): "BASED_IN",
    ("PERSON", "ISBN"): "AUTHORED",
    ("ORGANIZATION", "LOCATION"): "LOCATED_AT",
    ("ORGANIZATION", "ISBN"): "PUBLISHED",
    ("PERSON", "PHONE"): "HAS_PHONE",
    ("PERSON", "EMAIL"): "HAS_EMAIL",
    ("PERSON", "NATIONAL_ID"): "HAS_ID",
}


def group_by_anchor(found: list[Entity]) -> list[tuple[Entity, list[Entity]]]:
    """Attach each non-anchor entity to the closest anchor before it in the text."""
    ordered = sorted(found, key=lambda e: e.start)
    anchors = [e for e in ordered if e.entity_type in ANCHORS]
    members: list[list[Entity]] = [[] for _ in anchors]
    for e in ordered:
        if e.entity_type in ANCHORS or not anchors:
            continue
        before = [i for i, a in enumerate(anchors) if a.end <= e.start]
        members[before[-1] if before else 0].append(e)
    return list(zip(anchors, members, strict=True))


clusters = group_by_anchor(entities)
print("Step 3: clusters by anchor")
print("-" * 40)
for anchor, members in clusters:
    print(f"  {anchor.text} ({anchor.entity_type})")
    for m in members:
        rel = RELATION.get((anchor.entity_type, m.entity_type), "CO_MENTIONED")
        print(f"    --[{rel}]--> {m.text} ({m.entity_type})")
print()

# ---------------------------------------------------------------------------
# Step 4 -- the graph
# ---------------------------------------------------------------------------
G = nx.DiGraph()
for e in entities:
    G.add_node(e.text, label=e.text, entity_type=e.entity_type,
               confidence=e.confidence, source=e.source, **e.metadata)
for anchor, members in clusters:
    for m in members:
        relation = RELATION.get((anchor.entity_type, m.entity_type), "CO_MENTIONED")
        G.add_edge(anchor.text, m.text, relation=relation,
                   weight=min(anchor.confidence, m.confidence))
if len(isbns) >= 2:
    G.add_edge(isbns[0].text, isbns[1].text, relation="SAME_BOOK", weight=1.0)

print("Step 4: knowledge graph")
print("-" * 40)
print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
for u, v, d in G.edges(data=True):
    print(f"    {u} --[{d['relation']}]--> {v}  (weight={d['weight']:.2f})")
graph_json = json.dumps(nx.node_link_data(G, edges="edges"), indent=2)
print(f"  JSON export: {len(graph_json)} chars")
print()

# ---------------------------------------------------------------------------
# Step 5 -- an interactive page
# ---------------------------------------------------------------------------
COLORS = {"PERSON": "#4f46e5", "ORGANIZATION": "#0891b2", "LOCATION": "#059669",
          "ISBN": "#d97706", "DATE": "#dc2626"}
SHAPES = {"PERSON": "circle", "ORGANIZATION": "diamond", "LOCATION": "triangle", "ISBN": "box"}
EDGE_COLORS = {"AUTHORED": "#4f46e5", "PUBLISHED": "#0891b2", "LOCATED_AT": "#059669",
               "BASED_IN": "#059669", "SAME_BOOK": "#d97706", "CO_MENTIONED": "#e5e7eb",
               "HAS_ID": "#be185d", "AFFILIATED_WITH": "#1a56db"}


def graph_html(graph: nx.DiGraph, title: str = "arche identity knowledge graph") -> str:
    """A standalone vis.js page from the graph. Drag, zoom, hover for details."""
    nodes, edges = [], []
    for node_id, data in graph.nodes(data=True):
        kind = data.get("entity_type", "UNKNOWN")
        color = COLORS.get(kind, "#64748b")
        tip = [f"Type: {kind}", f"Confidence: {data.get('confidence', 0):.0%}",
               f"Source: {data.get('source', '')}"]
        if data.get("isbn_type"):
            tip.append(f"Format: {data['isbn_type']}")
        nodes.append({"id": node_id, "label": data.get("label", node_id),
                      "title": "\n".join(tip), "group": kind,
                      "shape": SHAPES.get(kind, "box"), "borderWidth": 2,
                      "size": 30 if kind == "PERSON" else 25,
                      "color": {"background": color + "30", "border": color},
                      "font": {"color": "#101828", "size": 14, "face": "Inter, sans-serif"}})
    for u, v, data in graph.edges(data=True):
        rel, weight = data.get("relation", "ASSOCIATED"), data.get("weight", 0.5)
        color = EDGE_COLORS.get(rel, "#94a3b8")
        edges.append({"from": u, "to": v, "label": rel,
                      "title": f"{rel} (weight {weight:.2f})",
                      "color": {"color": color, "highlight": color},
                      "width": max(1, int(weight * 3)),
                      "font": {"size": 10, "color": "#667085", "align": "middle"},
                      "smooth": {"type": "continuous"}})
    legend = "".join(
        '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:16px;">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{c};'
        f'display:inline-block;"></span>{k}</span>' for k, c in COLORS.items())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Inter, -apple-system, sans-serif; background: #f9fafb; color: #101828; }}
  .header {{ background: #101828; color: white; padding: 1.25rem 2rem;
             display: flex; justify-content: space-between;
             align-items: center; }}
  .header h1 {{ font-size: 1.3rem; font-weight: 400; }}
  .badge {{ background: #1a56db; color: white; padding: 0.25rem 0.75rem; border-radius: 4px;
            font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em; }}
  .toolbar {{ background: white; border-bottom: 1px solid #e5e7eb;
              padding: 0.75rem 2rem; display: flex; align-items: center;
              gap: 1.5rem; font-size: 0.85rem; color: #667085; }}
  .stat strong {{ color: #101828; font-size: 1rem; }}
  .legend {{ margin-left: auto; display: flex; align-items: center;
             font-size: 0.8rem; color: #344054; }}
  #graph {{ width: 100%; height: calc(100vh - 110px); }}
  .footer {{ position: fixed; bottom: 0; width: 100%; text-align: center;
             padding: 0.5rem; font-size: 0.7rem; color: #98a2b3;
             background: #f9fafb; border-top: 1px solid #f3f4f6; }}
</style>
</head>
<body>
<div class="header"><h1>{title}</h1>
  <span class="badge">arche-core {arche.__version__}</span></div>
<div class="toolbar">
  <span class="stat"><strong>{graph.number_of_nodes()}</strong> nodes</span>
  <span class="stat"><strong>{graph.number_of_edges()}</strong> edges</span>
  <span class="stat"><strong>{len(clusters)}</strong> clusters</span>
  <span class="legend">{legend}</span>
</div>
<div id="graph"></div>
<div class="footer">Entities from arche.extract (GliNER + regex validators).
  Drag nodes to rearrange, scroll to zoom, hover for details.</div>
<script>
  var nodes = new vis.DataSet({json.dumps(nodes)});
  var edges = new vis.DataSet({json.dumps(edges)});
  new vis.Network(document.getElementById("graph"), {{ nodes: nodes, edges: edges }}, {{
    physics: {{ solver: "forceAtlas2Based",
               forceAtlas2Based: {{ gravitationalConstant: -40, centralGravity: 0.005,
                                   springLength: 200, springConstant: 0.04, damping: 0.4 }},
               stabilization: {{ iterations: 150 }} }},
    nodes: {{ margin: 12,
             shadow: {{ enabled: true, size: 4, x: 2, y: 2, color: "rgba(0,0,0,0.1)" }} }},
    edges: {{ smooth: {{ type: "continuous" }},
             arrows: {{ to: {{ enabled: true, scaleFactor: 0.6 }} }} }},
    interaction: {{ hover: true, tooltipDelay: 100 }}
  }});
</script>
</body>
</html>"""


out = Path(__file__).parent / "identity_graph.html"
out.write_text(graph_html(G), encoding="utf-8")
print("Step 5: visualisation")
print("-" * 40)
print(f"  written to {out}")
print()
print("=" * 72)
print("Done. Open examples/identity_graph.html in a browser.")
print("=" * 72)
