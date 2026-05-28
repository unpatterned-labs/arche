# Copyright 2026 unpatterned.org
# ruff: noqa: E501 — HTML/CSV/JSON format strings use long template lines by design.
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

"""Visualization and formatting for arche output.

Provides multiple ways to display and export arche results:
- Rich tables (terminal)
- CSV export
- HTML entity cards
- Network graph (DOT/HTML)
- Tagged text (XML-style)
- Summary statistics

Usage:
    from arche import resolve
    from arche import print_table, to_csv, to_html, to_dot

    result = resolve("Fatima Abdullahi, NIN 12345678901")
    print_table(result)
    to_csv(result, "entities.csv")
    html = to_html(result)
    dot = to_dot(result)
"""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ensemble import IdentityEvidence
    from .pipeline import ResolutionResult


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════


def format_table(
    result: ResolutionResult,
    *,
    show_source: bool = False,
    show_spans: bool = False,
    max_text_width: int = 40,
) -> str:
    """Format a ResolutionResult as an ASCII table.

    Parameters
    ----------
    result:
        Pipeline result from ``resolve()``.
    show_source:
        Include the detection source column (gliner, regex, african).
    show_spans:
        Include start/end position columns.
    max_text_width:
        Maximum width for the text column.

    Returns
    -------
    str
        Formatted ASCII table string.
    """
    rows = []
    for e in result.entities:
        text = e.text[:max_text_width - 2] + ".." if len(e.text) > max_text_width else e.text
        row = {
            "type": e.entity_type,
            "text": text,
            "confidence": f"{e.confidence:.0%}",
        }
        if show_source:
            row["source"] = e.source
        if show_spans:
            row["start"] = str(e.start)
            row["end"] = str(e.end)
        rows.append(row)

    if not rows:
        return "(no entities found)"

    headers = list(rows[0].keys())
    col_widths = {h: max(len(h), max(len(r[h]) for r in rows)) for h in headers}

    lines = []
    header_line = "  ".join(h.upper().ljust(col_widths[h]) for h in headers)
    sep_line = "  ".join("-" * col_widths[h] for h in headers)
    lines.append(header_line)
    lines.append(sep_line)
    for row in rows:
        lines.append("  ".join(row[h].ljust(col_widths[h]) for h in headers))

    return "\n".join(lines)


def print_table(result: ResolutionResult, **kwargs) -> None:
    """Print a ResolutionResult as a formatted table to stdout."""
    print(format_table(result, **kwargs))


# ═══════════════════════════════════════════════════════════════════════════════
# EVIDENCE TABLE (for v2 ensemble output)
# ═══════════════════════════════════════════════════════════════════════════════


def format_evidence_table(
    evidence: list[IdentityEvidence],
    *,
    show_source: bool = True,
    max_text_width: int = 35,
) -> str:
    """Format IdentityEvidence list as an ASCII table.

    Parameters
    ----------
    evidence:
        List of IdentityEvidence from ``extract_identity_evidence()``.
    show_source:
        Include detector source column.
    max_text_width:
        Maximum width for the text column.
    """
    if not evidence:
        return "(no entities found)"

    rows = []
    for i, e in enumerate(evidence, 1):
        text = e.text[:max_text_width - 2] + ".." if len(e.text) > max_text_width else e.text
        row = {"#": str(i), "label": e.label, "text": text, "conf": f"{e.confidence:.0%}"}
        if show_source:
            row["source"] = e.detector_source
        rows.append(row)

    headers = list(rows[0].keys())
    col_widths = {h: max(len(h), max(len(r[h]) for r in rows)) for h in headers}

    lines = []
    lines.append("  ".join(h.upper().ljust(col_widths[h]) for h in headers))
    lines.append("  ".join("-" * col_widths[h] for h in headers))
    for row in rows:
        lines.append("  ".join(row[h].ljust(col_widths[h]) for h in headers))

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# CSV EXPORT
# ═══════════════════════════════════════════════════════════════════════════════


def to_csv(result: ResolutionResult, path: str | None = None) -> str:
    """Export entities to CSV format.

    Parameters
    ----------
    result:
        Pipeline result from ``resolve()``.
    path:
        If provided, write to this file path. Otherwise return as string.

    Returns
    -------
    str
        CSV content as a string.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["text", "entity_type", "confidence", "start", "end", "source"],
    )
    writer.writeheader()
    for e in result.entities:
        writer.writerow({
            "text": e.text,
            "entity_type": e.entity_type,
            "confidence": round(e.confidence, 4),
            "start": e.start,
            "end": e.end,
            "source": e.source,
        })

    content = buf.getvalue()
    if path:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    return content


def evidence_to_csv(evidence: list[IdentityEvidence], path: str | None = None) -> str:
    """Export IdentityEvidence to CSV format.

    Parameters
    ----------
    evidence:
        List from ``extract_identity_evidence()``.
    path:
        If provided, write to this file path.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["label", "text", "confidence", "start", "end", "detector_source",
                     "country_hint", "validator_status"],
    )
    writer.writeheader()
    for e in evidence:
        writer.writerow({
            "label": e.label,
            "text": e.text,
            "confidence": round(e.confidence, 4),
            "start": e.start,
            "end": e.end,
            "detector_source": e.detector_source,
            "country_hint": getattr(e, "country_hint", ""),
            "validator_status": getattr(e, "validator_status", ""),
        })

    content = buf.getvalue()
    if path:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    return content


# ═══════════════════════════════════════════════════════════════════════════════
# HTML OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

# Color palette for entity labels
_LABEL_COLORS = {
    "person": "#4f46e5",      # indigo
    "first_name": "#6366f1",  # indigo lighter
    "last_name": "#6366f1",
    "organization": "#0891b2", # cyan
    "location": "#059669",     # emerald
    "city": "#059669",
    "street_address": "#059669",
    "state": "#059669",
    "postcode": "#059669",
    "date": "#d97706",         # amber
    "money": "#dc2626",        # red
    "phone_number": "#7c3aed", # violet
    "national_id": "#be185d",  # pink
    "nin": "#be185d",
    "bvn": "#be185d",
    "email": "#7c3aed",
    "swift_bic": "#dc2626",
    "account_number": "#dc2626",
    "occupation": "#0284c7",   # sky
    "title": "#64748b",        # slate
    "time": "#d97706",
    # v1 entity types
    "PERSON": "#4f46e5",
    "ORGANIZATION": "#0891b2",
    "LOCATION": "#059669",
    "DATE": "#d97706",
    "MONEY": "#dc2626",
    "PHONE": "#7c3aed",
    "EMAIL": "#7c3aed",
    "NATIONAL_ID": "#be185d",
}


def to_html(
    result: ResolutionResult,
    *,
    title: str = "arche Analysis",
    include_pii: bool = True,
    include_signals: bool = True,
) -> str:
    """Generate a standalone HTML page visualizing the result.

    The HTML includes:
    - Entity cards with color-coded labels
    - PII detections with severity indicators
    - Signal alerts
    - Summary statistics

    Parameters
    ----------
    result:
        Pipeline result from ``resolve()``.
    title:
        Page title.
    include_pii:
        Include PII detections section.
    include_signals:
        Include signals section.

    Returns
    -------
    str
        Complete HTML page as a string.
    """
    entity_cards = []
    for e in result.entities:
        color = _LABEL_COLORS.get(e.entity_type, "#64748b")
        entity_cards.append(
            f'<div class="entity-card">'
            f'<span class="entity-label" style="background:{color}">{e.entity_type}</span>'
            f'<span class="entity-text">{_html_escape(e.text)}</span>'
            f'<span class="entity-conf">{e.confidence:.0%}</span>'
            f'</div>'
        )

    pii_rows = ""
    if include_pii and result.pii:
        for p in result.pii:
            pii_rows += (
                f"<tr><td>{_html_escape(p.pii_type)}</td>"
                f"<td>{_html_escape(p.text)}</td>"
                f"<td>{p.confidence:.0%}</td>"
                f"<td>{p.country or '-'}</td></tr>\n"
            )

    signal_items = ""
    if include_signals and result.signals:
        for s in result.signals:
            severity_color = {"high": "#dc2626", "medium": "#d97706", "low": "#059669"}.get(
                s.severity, "#64748b"
            )
            signal_items += (
                f'<div class="signal" style="border-left: 4px solid {severity_color}">'
                f'<strong>{s.signal_type}</strong> ({s.severity})<br>'
                f'{_html_escape(s.description)}'
                f'</div>\n'
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html_escape(title)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Inter, -apple-system, sans-serif; background: #f9fafb; color: #101828; padding: 2rem; max-width: 900px; margin: 0 auto; }}
  h1 {{ font-family: 'DM Serif Display', Georgia, serif; font-size: 1.5rem; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.1rem; margin: 1.5rem 0 0.75rem; color: #344054; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5rem; }}
  .summary {{ display: flex; gap: 1.5rem; margin: 1rem 0; }}
  .stat {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem 1.5rem; text-align: center; }}
  .stat-value {{ font-size: 1.5rem; font-weight: 700; color: #1a56db; }}
  .stat-label {{ font-size: 0.8rem; color: #667085; }}
  .entity-card {{ display: inline-flex; align-items: center; gap: 0.5rem; background: white; border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.4rem 0.8rem; margin: 0.25rem; }}
  .entity-label {{ color: white; font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }}
  .entity-text {{ font-weight: 500; }}
  .entity-conf {{ color: #667085; font-size: 0.8rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0; }}
  th {{ text-align: left; font-size: 0.75rem; color: #667085; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.5rem; border-bottom: 2px solid #e5e7eb; }}
  td {{ padding: 0.5rem; border-bottom: 1px solid #f3f4f6; font-size: 0.9rem; }}
  .signal {{ background: white; border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.75rem 1rem; margin: 0.5rem 0; font-size: 0.9rem; }}
  .footer {{ margin-top: 2rem; font-size: 0.75rem; color: #98a2b3; text-align: center; }}
</style>
</head>
<body>
<h1>{_html_escape(title)}</h1>

<div class="summary">
  <div class="stat"><div class="stat-value">{result.entity_count}</div><div class="stat-label">Entities</div></div>
  <div class="stat"><div class="stat-value">{result.duplicate_count}</div><div class="stat-label">Duplicates</div></div>
  <div class="stat"><div class="stat-value">{result.pii_count}</div><div class="stat-label">PII</div></div>
  <div class="stat"><div class="stat-value">{len(result.signals)}</div><div class="stat-label">Signals</div></div>
</div>

<h2>Entities</h2>
<div>{''.join(entity_cards)}</div>

{"<h2>PII Detections</h2><table><tr><th>Type</th><th>Value</th><th>Confidence</th><th>Country</th></tr>" + pii_rows + "</table>" if pii_rows else ""}

{"<h2>Signals</h2>" + signal_items if signal_items else ""}

<div class="footer">Generated by arche v0.1.0a2 &mdash; unpatterned.org</div>
</body>
</html>"""


def evidence_to_html(
    evidence: list[IdentityEvidence],
    text: str = "",
    *,
    title: str = "arche Extraction",
) -> str:
    """Generate HTML visualization for IdentityEvidence.

    Produces an annotated text view where each entity is highlighted inline
    with its label, plus a summary table below.

    Parameters
    ----------
    evidence:
        List from ``extract_identity_evidence()``.
    text:
        Original text to annotate (optional — enables inline highlighting).
    title:
        Page title.
    """
    # Build annotated text with inline highlights
    annotated = ""
    if text and evidence:
        sorted_ev = sorted(evidence, key=lambda e: e.start)
        last_end = 0
        for e in sorted_ev:
            if e.start < last_end:
                continue  # skip overlapping
            color = _LABEL_COLORS.get(e.label, "#64748b")
            annotated += _html_escape(text[last_end:e.start])
            annotated += (
                f'<mark style="background:{color}20; border-bottom: 2px solid {color}; '
                f'padding: 0.1rem 0.2rem; border-radius: 3px;" '
                f'title="{e.label} ({e.confidence:.0%})">'
                f'{_html_escape(e.text)}'
                f'<sup style="color:{color}; font-size:0.65rem; font-weight:600;">'
                f'{e.label}</sup></mark>'
            )
            last_end = e.end
        annotated += _html_escape(text[last_end:])

    # Build summary table
    table_rows = ""
    for i, e in enumerate(evidence, 1):
        color = _LABEL_COLORS.get(e.label, "#64748b")
        table_rows += (
            f"<tr><td>{i}</td>"
            f'<td><span style="background:{color}; color:white; padding:0.1rem 0.4rem; '
            f'border-radius:3px; font-size:0.75rem;">{e.label}</span></td>'
            f"<td>{_html_escape(e.text)}</td>"
            f"<td>{e.confidence:.0%}</td>"
            f"<td>{e.detector_source}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html_escape(title)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Inter, -apple-system, sans-serif; background: #f9fafb; color: #101828; padding: 2rem; max-width: 900px; margin: 0 auto; }}
  h1 {{ font-family: 'DM Serif Display', Georgia, serif; font-size: 1.5rem; margin-bottom: 1rem; }}
  h2 {{ font-size: 1.1rem; margin: 1.5rem 0 0.75rem; color: #344054; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5rem; }}
  .annotated {{ background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1.5rem; line-height: 2; font-size: 0.95rem; margin: 1rem 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0; }}
  th {{ text-align: left; font-size: 0.75rem; color: #667085; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.5rem; border-bottom: 2px solid #e5e7eb; }}
  td {{ padding: 0.5rem; border-bottom: 1px solid #f3f4f6; font-size: 0.9rem; }}
  .footer {{ margin-top: 2rem; font-size: 0.75rem; color: #98a2b3; text-align: center; }}
</style>
</head>
<body>
<h1>{_html_escape(title)}</h1>
<p style="color:#667085; margin-bottom:1rem;">{len(evidence)} entities extracted</p>

{"<h2>Annotated Text</h2><div class='annotated'>" + annotated + "</div>" if annotated else ""}

<h2>Entity Table</h2>
<table>
<tr><th>#</th><th>Label</th><th>Text</th><th>Confidence</th><th>Source</th></tr>
{table_rows}
</table>

<div class="footer">Generated by arche v0.1.0a2 &mdash; unpatterned.org</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# NETWORK GRAPH (DOT format for Graphviz / HTML for vis.js)
# ═══════════════════════════════════════════════════════════════════════════════


def to_dot(result: ResolutionResult) -> str:
    """Export the entity graph as Graphviz DOT format.

    Can be rendered with ``dot -Tpng graph.dot -o graph.png`` or
    pasted into an online Graphviz viewer.

    Parameters
    ----------
    result:
        Pipeline result from ``resolve()`` with ``build_knowledge_graph=True``.
    """
    lines = ['digraph arche {', '  rankdir=LR;', '  node [shape=box, style=filled, fontname="Inter"];']

    # Entity nodes
    for i, e in enumerate(result.entities):
        color = _LABEL_COLORS.get(e.entity_type, "#64748b")
        label = f"{e.entity_type}\\n{e.text}"
        lines.append(f'  entity_{i} [label="{label}", fillcolor="{color}30", color="{color}"];')

    # Resolution edges (SAME_AS)
    for r in result.resolved:
        if r.sources > 1:
            lines.append(f'  // Resolved: {r.canonical_name} ({r.sources} sources)')

    # PII edges
    for i, p in enumerate(result.pii):
        lines.append(f'  pii_{i} [label="PII\\n{p.pii_type}", shape=diamond, fillcolor="#fef2f2", color="#dc2626"];')

    lines.append("}")
    return "\n".join(lines)


def to_graph_html(result: ResolutionResult, *, title: str = "arche Entity Graph") -> str:
    """Generate an interactive HTML network graph using vis.js (CDN).

    The graph shows entities as nodes and relationships as edges.
    Nodes are color-coded by entity type. The graph is interactive
    (drag, zoom, hover for details).

    Parameters
    ----------
    result:
        Pipeline result from ``resolve()``.
    title:
        Page title.

    Returns
    -------
    str
        Standalone HTML page with embedded vis.js graph.
    """
    nodes = []
    edges = []

    # Entity nodes
    for i, e in enumerate(result.entities):
        color = _LABEL_COLORS.get(e.entity_type, "#64748b")
        nodes.append({
            "id": i,
            "label": e.text,
            "title": f"{e.entity_type} ({e.confidence:.0%})\nSource: {e.source}",
            "group": e.entity_type,
            "color": {"background": color + "30", "border": color},
            "font": {"color": "#101828"},
        })

    # Co-occurrence edges (entities from the same text)
    for i in range(len(result.entities)):
        for j in range(i + 1, len(result.entities)):
            ei, ej = result.entities[i], result.entities[j]
            if ei.entity_type != ej.entity_type:
                edges.append({
                    "from": i, "to": j,
                    "color": {"color": "#e5e7eb"},
                    "width": 1,
                    "title": "co-mentioned",
                })

    # Resolution edges (same person)
    for r in result.resolved:
        if r.sources > 1 and hasattr(r, "entities") and len(r.entities) > 1:
            base = None
            for i, e in enumerate(result.entities):
                if e.text == r.canonical_name:
                    base = i
                    break
            if base is not None:
                for i, e in enumerate(result.entities):
                    if i != base and e.text in r.aliases:
                        edges.append({
                            "from": base, "to": i,
                            "color": {"color": "#1a56db"},
                            "width": 3,
                            "label": "SAME_AS",
                            "title": f"Resolved: {r.confidence:.0%}",
                        })

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html_escape(title)}</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin: 0; font-family: Inter, sans-serif; }}
  #title {{ padding: 1rem 2rem; background: #101828; color: white; font-size: 1.1rem; }}
  #graph {{ width: 100%; height: calc(100vh - 56px); }}
</style>
</head>
<body>
<div id="title">{_html_escape(title)} &mdash; {len(result.entities)} entities</div>
<div id="graph"></div>
<script>
  var nodes = new vis.DataSet({nodes_json});
  var edges = new vis.DataSet({edges_json});
  var container = document.getElementById("graph");
  var data = {{ nodes: nodes, edges: edges }};
  var options = {{
    physics: {{ solver: "forceAtlas2Based", forceAtlas2Based: {{ gravitationalConstant: -30 }} }},
    nodes: {{ shape: "box", margin: 10, font: {{ size: 14 }} }},
    edges: {{ smooth: {{ type: "continuous" }} }},
    interaction: {{ hover: true, tooltipDelay: 100 }},
  }};
  new vis.Network(container, data, options);
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════


def format_summary(result: ResolutionResult) -> str:
    """Generate a one-line human-readable summary of the result.

    Example:
        "Found 4 entities (2 PERSON, 1 NATIONAL_ID, 1 PHONE). Resolved 1 identity.
         Detected 2 PII items. 1 signal: FINANCIAL_FLAG (medium)."
    """
    # Count entity types
    type_counts: dict[str, int] = {}
    for e in result.entities:
        type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1
    type_summary = ", ".join(f"{count} {etype}" for etype, count in type_counts.items())

    parts = [f"Found {result.entity_count} entities ({type_summary})."]

    if result.duplicate_count:
        parts.append(f"Resolved {result.duplicate_count} duplicate(s).")

    if result.pii_count:
        parts.append(f"Detected {result.pii_count} PII item(s).")

    if result.signals:
        sig_summary = ", ".join(f"{s.signal_type} ({s.severity})" for s in result.signals)
        parts.append(f"{len(result.signals)} signal(s): {sig_summary}.")

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
