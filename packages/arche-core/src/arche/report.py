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

import html
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


def _sensitive_ids(records: list[dict]) -> int:
    n = 0
    for r in records:
        rid = re.sub(r"[\s-]", "", str(r.get("id", "")))
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


def _record_cell(rec: dict | None, reveal: bool) -> str:
    if rec is None:
        return '<span class="mute">record not found</span>'
    shown = render(rec, reveal=True if reveal else ["id"])
    parts = []
    for k, v in shown.items():
        if k == "id":
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
    if not reveal:
        hot = _sensitive_ids(records_a) + _sensitive_ids(records_b)
        if hot:
            raise ValueError(
                f"{hot} record id(s) look like sensitive identifiers "
                "(9+ digit runs, the shape of a national ID). A masked report "
                "displays row ids, so this would leak them. Use a surrogate "
                "row id column, or generate a revealed working copy locally."
            )
    by_a = {str(r.get("id")): r for r in records_a}
    by_b = {str(r.get("id")): r for r in records_b}
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
            f'{_record_cell(by_a.get(str(m.get("a_id"))), reveal)}</div></td>'
            f'<td class="arrow">&#8596;</td>'
            f'<td class="idcol">{_esc(m.get("b_id"))}<div class="rec">'
            f'{_record_cell(by_b.get(str(m.get("b_id"))), reveal)}</div></td>'
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
