# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Shareable crosswalk reports — the artifact ``arche compare`` emits.

One self-contained HTML file (inline CSS, no external requests) that a
reviewer can open, forward, or print to PDF. The report is **masked by
default**: record values pass through :func:`arche.render.render`'s
fail-safe allowlist, so the artifact people share is the safe one.
``reveal=True`` produces a local working copy. Row ids stay readable
(they are already plaintext in the crosswalk result itself).
"""

from __future__ import annotations

import hashlib as _hashlib
import html
import json as _json
import re
from datetime import UTC, datetime
from typing import Any

from arche.render import render
from arche.resolve._gate import DISTINCTIVE_FLOOR

# Row ids are displayed in masked mode (they are the join keys a reviewer
# needs), which makes an ID column that is ITSELF sensitive — a NIN, BVN, or
# SSN used as the row key — a leak vector. Nine-plus digit runs are the shape
# of every such identifier arche knows; masked-mode generation refuses them.
_SENSITIVE_ID = re.compile(r"^\d{9,}$")

# A brand color is interpolated into a <style> block, which makes it a CSS
# injection vector unless strictly validated: hex colors only, nothing else.
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")


def _sensitive_ids(records: list[dict], id_field: str = "id") -> int:
    n = 0
    for r in records:
        rid = re.sub(r"[\s-]", "", str(r.get(id_field, "")))
        if _SENSITIVE_ID.match(rid):
            n += 1
    return n

_INK = "#101828"
_BLUE = "#1a56db"
_MUTE = "#667085"
_LINE = "#e4e7ec"
_BG = "#f9fafb"


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("arche-core")
    except Exception:  # pragma: no cover - metadata absent in odd envs
        return "unknown"


def _record_cell(rec: dict | None, reveal: bool, decl=None,
                 id_field: str = "id") -> str:
    if rec is None:
        return '<span class="mute">record not found</span>'
    shown = render(rec, reveal=True if reveal else [id_field], decl=decl)
    parts = []
    for k, v in shown.items():
        if k == id_field:
            continue
        parts.append(f'<span class="kv"><b>{_esc(k)}</b> {_esc(v)}</span>')
    return " ".join(parts) or '<span class="mute">no fields</span>'


def _evidence_bars(evidence: dict[str, float] | None) -> str:
    if not evidence:
        return ""
    rows = []
    for name, score in sorted(evidence.items(), key=lambda kv: -kv[1]):
        pct = max(0.0, min(1.0, float(score))) * 100
        rows.append(
            f'<div class="ev"><span class="evname">{_esc(name)}</span>'
            f'<span class="evtrack"><span class="evfill" '
            f'style="width:{pct:.0f}%"></span></span>'
            f'<span class="evval">{float(score):.2f}</span></div>'
        )
    return "".join(rows)


def crosswalk_report(
    result: dict,
    records_a: list[dict],
    records_b: list[dict],
    *,
    reveal: bool = False,
    title: str = "arche compare",
    entity: str | None = None,
    meta: dict[str, Any] | None = None,
    brand_color: str | None = None,
    decl=None,
    id_field: str = "id",
) -> str:
    """Render a crosswalk ``result`` into one self-contained HTML report.

    Raises :class:`ValueError` in masked mode when record ids themselves look
    like sensitive identifiers (nine-plus digit runs — the shape of a NIN,
    BVN, or SSN): a "masked" report that prints national IDs as row keys is a
    leak, so we refuse rather than launder. Use a surrogate row id, or
    generate an explicitly revealed working copy locally.

    ``brand_color`` themes the report's accent (stat numbers, chips, evidence
    bars). Hex colors only — the value lands inside a ``<style>`` block, so
    anything else is refused as a CSS-injection risk.
    """
    if brand_color is not None and not _HEX_COLOR.match(brand_color):
        raise ValueError(
            f"brand_color must be a hex color like #1a56db, got {brand_color!r}"
        )
    accent = brand_color or _BLUE
    if decl is not None and id_field == "id":
        id_field = decl.id_field
    if not reveal:
        hot = _sensitive_ids(records_a, id_field) + _sensitive_ids(records_b, id_field)
        if hot:
            raise ValueError(
                f"{hot} record id(s) look like sensitive identifiers "
                "(9+ digit runs, the shape of a national ID). A masked report "
                "displays row ids, so this would leak them. Use a surrogate "
                "row id column, or generate a revealed working copy locally."
            )
    by_a = {str(r.get(id_field)): r for r in records_a}
    by_b = {str(r.get(id_field)): r for r in records_b}
    matches = [m for m in result.get("matches", []) if m.get("decision") == "match"]
    review = [m for m in result.get("matches", []) if m.get("decision") != "match"]
    blocking = result.get("blocking") or {}
    reduction = blocking.get("reduction_ratio")
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    disclosure = "revealed (working copy)" if reveal else "masked (safe to share)"

    def row(m: dict) -> str:
        chip = m.get("decision", "?")
        chip_cls = "match" if chip == "match" else "review"
        return (
            "<tr>"
            f'<td class="idcol">{_esc(m.get("a_id"))}<div class="rec">'
            f'{_record_cell(by_a.get(str(m.get("a_id"))), reveal, decl, id_field)}</div></td>'
            f'<td class="arrow">&#8596;</td>'
            f'<td class="idcol">{_esc(m.get("b_id"))}<div class="rec">'
            f'{_record_cell(by_b.get(str(m.get("b_id"))), reveal, decl, id_field)}</div></td>'
            f'<td><span class="chip {chip_cls}">{_esc(chip)}</span>'
            f'<div class="score">{float(m.get("score", 0)):.3f}</div></td>'
            f'<td class="evcol">{_evidence_bars(m.get("evidence"))}</td>'
            "</tr>"
        )

    def table(rows: list[dict], empty: str) -> str:
        if not rows:
            return f'<p class="mute">{empty}</p>'
        body = "".join(row(m) for m in rows)
        return (
            '<table><thead><tr><th>left</th><th></th><th>right</th>'
            "<th>decision</th><th>evidence</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    stats = [
        (f"{len(records_a):,} × {len(records_b):,}", "records compared"),
        (f"{len(matches):,}", "matched"),
        (f"{len(review):,}", "for human review"),
    ]
    if reduction is not None:
        stats.append((f"{float(reduction) * 100:.1f}%", "pairs skipped by blocking"))

    stat_html = "".join(
        f'<div class="stat"><div class="n">{_esc(n)}</div>'
        f'<div class="l">{_esc(label)}</div></div>'
        for n, label in stats
    )
    # Caller meta first; assurance fields last so they can never be overwritten.
    meta_rows = {
        **(meta or {}),
        "generated": generated,
        "arche-core": _version(),
        "entity pack": entity or "custom comparators",
        "distinctive-evidence gate": f"no merge below {DISTINCTIVE_FLOOR} distinctiveness",
        "disclosure": disclosure,
    }
    meta_html = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>" for k, v in meta_rows.items()
    )
    mask_note = (
        ""
        if reveal
        else '<p class="note">Values are masked by default so this file is safe to '
        "share; evidence and scores are the argument. Regenerate with "
        "<code>--reveal</code> for a local working copy.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ font-family: 'Segoe UI', Helvetica, Arial, sans-serif; color: {_INK};
         background: {_BG}; padding: 32px; }}
  .card {{ background: white; border: 1px solid {_LINE}; border-radius: 12px;
          max-width: 1080px; margin: 0 auto; padding: 36px 40px; }}
  h1 {{ font-size: 24px; }} h2 {{ font-size: 15px; margin: 28px 0 10px;
       text-transform: uppercase; letter-spacing: .06em; color: {_MUTE}; }}
  .sub {{ color: {_MUTE}; font-size: 13px; margin-top: 6px; }}
  .stats {{ display: flex; gap: 14px; flex-wrap: wrap; margin-top: 22px; }}
  .stat {{ border: 1px solid {_LINE}; border-radius: 10px; padding: 14px 18px;
          min-width: 150px; }}
  .stat .n {{ font-size: 22px; font-weight: 700; color: {accent};
             font-variant-numeric: tabular-nums; }}
  .stat .l {{ font-size: 12px; color: {_MUTE}; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: {_MUTE}; font-weight: 600; font-size: 11px;
       text-transform: uppercase; letter-spacing: .05em; padding: 8px 10px;
       border-bottom: 1px solid {_LINE}; }}
  td {{ padding: 10px; border-bottom: 1px solid {_LINE}; vertical-align: top; }}
  .idcol {{ font-weight: 600; white-space: nowrap; }}
  .rec {{ font-weight: 400; margin-top: 4px; max-width: 320px; white-space: normal; }}
  .kv {{ display: inline-block; background: {_BG}; border: 1px solid {_LINE};
        border-radius: 6px; padding: 1px 7px; margin: 1px 2px 1px 0;
        font-size: 12px; }}
  .kv b {{ color: {_MUTE}; font-weight: 600; margin-right: 4px; }}
  .arrow {{ color: {_MUTE}; }}
  .chip {{ border-radius: 99px; padding: 2px 11px; font-size: 12px;
          font-weight: 600; }}
  .chip.match {{ background: color-mix(in srgb, {accent} 12%, white); color: {accent}; }}
  .chip.review {{ background: #fef4e6; color: #b54708; }}
  .score {{ color: {_MUTE}; font-size: 12px; margin-top: 5px;
           font-variant-numeric: tabular-nums; }}
  .evcol {{ min-width: 220px; }}
  .ev {{ display: flex; align-items: center; gap: 7px; margin: 2px 0; }}
  .evname {{ font-size: 11px; color: {_MUTE}; width: 78px; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap; }}
  .evtrack {{ flex: 1; height: 6px; background: {_BG}; border-radius: 4px;
             overflow: hidden; }}
  .evfill {{ display: block; height: 100%; background: {accent}; }}
  .evval {{ font-size: 11px; color: {_MUTE}; width: 32px; text-align: right;
           font-variant-numeric: tabular-nums; }}
  .mute {{ color: {_MUTE}; }}
  .note {{ font-size: 12.5px; color: {_MUTE}; background: {_BG};
          border: 1px solid {_LINE}; border-radius: 8px; padding: 10px 14px;
          margin-top: 16px; }}
  .prov td {{ font-size: 12px; color: {_MUTE}; padding: 5px 10px; }}
  .prov td:first-child {{ font-weight: 600; width: 220px; }}
  footer {{ margin-top: 26px; font-size: 12px; color: {_MUTE}; }}
  @media print {{ body {{ background: white; padding: 0; }}
    .card {{ border: none; padding: 0; }} tr {{ page-break-inside: avoid; }} }}
</style></head>
<body><div class="card">
  <h1>{_esc(title)}</h1>
  <div class="sub">Every decision below carries its evidence; nothing merged
  without distinctive agreement.</div>
  <div class="stats">{stat_html}</div>
  {mask_note}
  <h2>Matched</h2>
  {table(matches, "No pairs cleared the gate.")}
  <h2>Review queue</h2>
  {table(review, "Nothing routed to review.")}
  <h2>Method &amp; provenance</h2>
  <table class="prov">{meta_html}</table>
  <footer>Generated by <b>arche</b> — know the real-world entity, prove the
  decision. The JSON sidecar is a working file for machines; this HTML is the
  share artifact. Print this page for a PDF copy.</footer>
</div></body></html>
"""


# ===================================================================
# Review packs — the artifact a reviewer adjudicates
# ===================================================================

# The four columns a reviewer fills, and the only vocabulary the outcome column
# accepts. Kept identical to `tools/arche-studio/state.py`: a pack whose
# outcomes the studio rejects is a pack nobody can adjudicate.
REVIEW_FIELDS = ("review_outcome", "reviewer", "reviewed_at", "reason")
REVIEW_OUTCOMES = ("same_entity", "different", "unresolved")
PACK_SCHEMA = "arche.review_pack.v1"


def pack_content_digest(rows: list[dict], fields: list[str]) -> str:
    """sha256 over the matcher's half of a pack: every column a reviewer does not fill.

    The manifest used to carry a digest of the decision ids and nothing else.
    That detects a row added or dropped and misses every edit inside a row:
    change every name in the pack, flip a decision, rewrite the evidence, and
    the id digest still matches. It was a queue-membership digest wearing the
    word integrity, and the docs around it claimed more than it did.

    This covers content. The four `REVIEW_FIELDS` are excluded deliberately,
    because a reviewer filling them in is the pack being used rather than
    altered, and a digest that moved when somebody did their job would be
    checked once and then ignored.

    Rows are sorted before hashing, so re-sorting a pack in a spreadsheet is not
    an alarm. Anything that changes a value, adds a row, or drops one is.

    Recomputable from the CSV alone, which is the point: a reviewer who was not
    there can read the pack, call this, and compare it with the manifest.
    """
    covered = [f for f in fields if f not in REVIEW_FIELDS]
    payload = sorted(
        ["" if r.get(f) is None else str(r.get(f, "")) for f in covered]
        for r in rows
    )
    canonical = _json.dumps([covered, payload], sort_keys=True,
                            separators=(",", ":"), ensure_ascii=False)
    return _hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def review_pack(
    result: dict,
    records_a: list[dict],
    records_b: list[dict],
    *,
    out_dir: Any,
    reveal: bool = False,
    sides: tuple[str, str] = ("a", "b"),
    entity: str | None = None,
    decisions: tuple[str, ...] = ("match", "review"),
    id_field: str = "id",
    decl=None,
    meta: dict[str, Any] | None = None,
) -> dict:
    """Write a crosswalk ``result`` as a review pack, and return its manifest.

    The machine-readable sibling of :func:`crosswalk_report`. That one produces
    an artifact to *read*; this produces one to *work*, in the shape
    ``tools/arche-studio`` opens::

        out_dir/pack.csv        one row per decision, four blank review columns
        out_dir/manifest.json   what was run, and a digest of the decision ids

    Point the studio at the directory and the pack appears in its picker.

    Columns are ``decision_id``, ``decision``, ``score``, then the two sides
    prefixed by ``sides`` (``a_name``, ``b_name``, ...), then ``evidence`` as
    JSON, then the four empty review columns. The studio infers which columns
    belong to which side from those prefixes, so two records that share a field
    name stay distinguishable.

    **Masked by default, like the report.** A pack is a file that gets copied
    around, so the fail-safe applies here too: record values pass through
    :func:`arche.render.render`, and record ids that look like national
    identifiers are refused outright. But a masked pack is close to useless for
    the thing a pack is *for*, since nobody can judge whether two people are the
    same when both names are redacted. Pass ``reveal=True`` for a working copy
    and keep it local. ``data/review_packs/`` is the intended home.

    ``decisions`` selects which rows to write. The default carries ``match`` and
    ``review`` and drops ``no_match``, because a queue of things the engine
    already rejected is not a queue. Pass a wider tuple to audit those too.
    """
    import csv
    import hashlib
    import json
    from pathlib import Path

    if len(sides) != 2 or sides[0] == sides[1]:
        raise ValueError(f"sides must be two distinct prefixes, got {sides!r}")
    for side in sides:
        if not side or "_" in side:
            raise ValueError(
                f"side prefix {side!r} must be non-empty and contain no "
                "underscore: the reviewer UI splits column names on the first "
                "underscore to tell the two records apart"
            )
    if decl is not None and id_field == "id":
        id_field = decl.id_field
    if not reveal:
        hot = _sensitive_ids(records_a, id_field) + _sensitive_ids(records_b, id_field)
        if hot:
            raise ValueError(
                f"{hot} record id(s) look like sensitive identifiers "
                "(9+ digit runs, the shape of a national ID). A pack carries "
                "row ids in plain text, so this would leak them. Use a "
                "surrogate row id column, or write a revealed working copy "
                "locally with reveal=True."
            )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    by_a = {str(r.get(id_field)): r for r in records_a}
    by_b = {str(r.get(id_field)): r for r in records_b}
    edges = [e for e in result.get("matches", []) if e.get("decision") in decisions]

    def shown(rec: dict | None) -> dict:
        if rec is None:
            return {}
        return render(rec, reveal=True if reveal else [id_field], decl=decl)

    # Column order is fixed rather than derived, so two packs of the same entity
    # diff against each other cleanly.
    rows: list[dict[str, Any]] = []
    side_keys: dict[str, list[str]] = {sides[0]: [], sides[1]: []}
    for edge in edges:
        rec_a = shown(by_a.get(str(edge.get("a_id"))))
        rec_b = shown(by_b.get(str(edge.get("b_id"))))
        row: dict[str, Any] = {
            "decision_id": edge.get("decision_id", ""),
            "decision": edge.get("decision", ""),
            "score": edge.get("score", ""),
            "distinctive_max": edge.get("distinctive_max", ""),
        }
        evidence = edge.get("evidence") or {}
        if "distance_km" in evidence:
            row["distance_km"] = evidence["distance_km"]
        for prefix, rec, rid in ((sides[0], rec_a, edge.get("a_id")),
                                 (sides[1], rec_b, edge.get("b_id"))):
            row[f"{prefix}_{id_field}"] = rid
            for k, v in rec.items():
                if k == id_field:
                    continue
                row[f"{prefix}_{k}"] = v
                if f"{prefix}_{k}" not in side_keys[prefix]:
                    side_keys[prefix].append(f"{prefix}_{k}")
        row["evidence"] = json.dumps(evidence, sort_keys=True)
        for name in REVIEW_FIELDS:
            row[name] = ""
        rows.append(row)

    head = ["decision_id", "decision", "score", "distinctive_max"]
    if any("distance_km" in r for r in rows):
        head.append("distance_km")
    fields = (head
              + [f"{sides[0]}_{id_field}"] + sorted(side_keys[sides[0]])
              + [f"{sides[1]}_{id_field}"] + sorted(side_keys[sides[1]])
              + ["evidence", *REVIEW_FIELDS])

    with (out / "pack.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({f: r.get(f, "") for f in fields})

    ids = [str(r["decision_id"]) for r in rows]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    manifest: dict[str, Any] = {
        "schema": PACK_SCHEMA,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arche_version": _version(),
        "entity": entity,
        "rows": len(rows),
        "decisions": counts,
        "disclosure": "revealed (working copy)" if reveal else "masked",
        "review_fields": list(REVIEW_FIELDS),
        "review_outcomes": list(REVIEW_OUTCOMES),
        # What is in the pack. Any value changed, any row added or dropped,
        # moves this. Recomputable from the CSV alone with
        # `arche.report.pack_content_digest`.
        "content_sha256": pack_content_digest(rows, fields),
        # Which decisions are in the pack. Membership only, and named for
        # what it is: it does not notice an edit inside a row, which is why
        # the digest above exists.
        "decision_ids_sha256": hashlib.sha256(
            "\n".join(sorted(ids)).encode()).hexdigest(),
        # Enough to say which engine produced this.
        "pins": result.get("pins") or {},
        "blocking": result.get("blocking") or {},
    }
    if meta:
        manifest["meta"] = meta
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


# ===================================================================
# `report(obj, format=...)` — one verb over eleven formatters
# ===================================================================
# The eleven were never eleven jobs. They are a small matrix that Python has no
# overloading to express, so the input type ended up encoded in the name:
#
#                        csv        html             table
#   ResolutionResult     to_csv     to_html          format_table
#   list[Evidence]       evidence_  evidence_        format_evidence_
#                          to_csv     to_html          table
#
# plus `to_dot` and `to_graph_html` (result only), `format_tagged_text`
# (evidence only), `format_summary`, and `print_table`, which is `format_table`
# followed by print.
#
# A caller holding an object and wanting CSV should not have to know which
# prefix their object earned. `report` dispatches on the type it is handed and
# raises with the available formats when a combination does not exist -- rather
# than, say, quietly returning a table when asked for a graph.
#
# Every one of the eleven still works and is still exported. This is one name
# over them, not a replacement of them.

#: (type key, format) -> the function that does it. Kept explicit rather than
#: derived: a table that can be read is worth more here than one that is clever,
#: and the gaps in it are real (a list of evidence spans has no entity graph to
#: draw, so there is no `dot` row for it).
_REPORTERS: dict[tuple[str, str], tuple[str, str]] = {
    ("result", "csv"): (".workflow._format", "to_csv"),
    ("result", "html"): (".workflow._format", "to_html"),
    ("result", "table"): (".workflow._format", "format_table"),
    ("result", "summary"): (".workflow._format", "format_summary"),
    ("result", "dot"): (".workflow._format", "to_dot"),
    ("result", "graph"): (".workflow._format", "to_graph_html"),
    ("evidence", "csv"): (".workflow._format", "evidence_to_csv"),
    ("evidence", "html"): (".workflow._format", "evidence_to_html"),
    ("evidence", "table"): (".workflow._format", "format_evidence_table"),
    ("evidence", "tagged"): (".ensemble", "format_tagged_text"),
}


def _kind_of(obj) -> str:
    """Which row of the matrix ``obj`` belongs to."""
    if isinstance(obj, list):
        return "evidence"
    if hasattr(obj, "entities"):
        return "result"
    raise TypeError(
        f"report() does not know how to describe a {type(obj).__name__}. It "
        "takes a ResolutionResult, or a list of IdentityEvidence. A Pipeline "
        "`Result` carries `detections` rather than `entities` and these "
        "formatters cannot read it -- an earlier version of this check "
        "accepted one and failed inside the formatter instead, which is a "
        "worse place to find out."
    )


def report(obj, format: str = "table", **kwargs):
    """Describe a result or a list of evidence, in the format you ask for.

    ``format`` is one of ``table``, ``summary``, ``csv``, ``html``, ``dot``,
    ``graph`` or ``tagged`` -- not all of which apply to both inputs, because
    a list of evidence spans has no entity graph to draw. Asking for one that
    does not apply raises and lists what does.

    Keyword arguments pass through to the underlying formatter unchanged.
    """
    from importlib import import_module

    kind = _kind_of(obj)
    target = _REPORTERS.get((kind, format))
    if target is None:
        available = sorted(f for k, f in _REPORTERS if k == kind)
        raise ValueError(
            f"format {format!r} is not available for {kind}; "
            f"available: {', '.join(available)}"
        )
    module = import_module(target[0], package="arche")
    return getattr(module, target[1])(obj, **kwargs)


# `arche.report` is a module AND this verb. Same collision `arche.extract` had
# and `arche.detect` documented: importing any name out of the submodule
# rebinds the package attribute from the function to the module, after which
# calling it raises TypeError. Making the module callable means it stops
# mattering which one the name resolved to.
import sys as _sys
from types import ModuleType as _ModuleType


class _CallableReportModule(_ModuleType):
    """``arche.report`` — the module, and the verb, under one name."""

    def __call__(self, *args, **kwargs):  # type: ignore[override]
        return report(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableReportModule
