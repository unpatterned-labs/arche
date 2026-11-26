# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Check mode: a person says whether a proposed reading of a text is right.

Label mode makes gold from nothing and never shows a model's output. Check mode
is the other job: a model, a parser or another person has proposed a reading,
and a person decides whether it holds. Keeping the two apart keeps each honest.

A **check pack** is a directory holding:

* ``pack.json``::

      {"schema": "arche.check_pack.v1",
       "title": "Time readings",
       "id_field": "id",
       "text_field": "text",               # the text the reading is about
       "proposal_field": "proposal",       # the reading to check, in plain words
       "mark_field": "words",              # optional: the words it is about, highlighted
       "occurrence_field": "n",            # optional: which occurrence of them (1 = first)
       "context_fields": ["written"],      # optional: shown above the text
       "control_field": "control",         # optional, never shown: 1 = wrong on purpose
       "guide": "GUIDE.md",                # optional
       "group_field": "country",           # optional, a column to filter by
       "export": "checks.csv"}             # optional, where Export writes

* ``items.csv``: one row per item.

A **control** is a reading made wrong on purpose. The checker is told that some
exist, never which. The export reports how many were caught, so a run of
approvals can be read for what it is: a check, if the controls were caught; a
glance, if they were not. Each save also records the seconds the item was on
screen, for the same reason.

Each save is one appended line in ``<studio home>/_studio/checks/<pack>.jsonl``;
the latest line per item stands. The pack itself is never written to, except by
Export.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import statistics
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "arche.check_pack.v1"
VERDICTS = ("right", "wrong", "unsure")
#: An item answered faster than this is reported as too quick to have been read.
FAST_SECONDS = 3.0
_LOCK = threading.Lock()


class CheckError(ValueError):
    """A check pack or a check that cannot be accepted."""


def root(home: Path) -> Path:
    env = os.environ.get("ARCHE_CHECK_PACKS")
    return Path(env).expanduser() if env else home / "check_packs"


def _state_file(home: Path, pack: str) -> Path:
    return home / "_studio" / "checks" / f"{pack}.jsonl"


def _spec(directory: Path) -> dict[str, Any]:
    spec = json.loads((directory / "pack.json").read_text(encoding="utf-8"))
    if spec.get("schema") != SCHEMA:
        raise CheckError(f"{directory.name}: pack.json schema must be {SCHEMA}")
    for f in ("id_field", "text_field", "proposal_field"):
        if not spec.get(f):
            raise CheckError(f"{directory.name}: pack.json needs {f}")
    ctx = spec.get("context_fields", [])
    if not isinstance(ctx, list) or not all(isinstance(c, str) for c in ctx):
        raise CheckError(f"{directory.name}: context_fields is a list of column names")
    return spec


def _items(d: Path, spec: dict) -> list[dict[str, str]]:
    with (d / "items.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r[spec["id_field"]] for r in rows]
    if len(set(ids)) != len(ids):
        raise CheckError(f"{d.name}: item ids are not unique")
    need = [spec["text_field"], spec["proposal_field"], *spec.get("context_fields", []),
            *(spec[k] for k in ("mark_field", "occurrence_field", "control_field", "group_field")
              if spec.get(k))]
    for r in rows:
        for f in need:
            if f not in r:
                raise CheckError(f"{d.name}: items.csv has no {f!r} column")
    return rows


def packs(home: Path) -> list[dict[str, Any]]:
    out = []
    base = root(home)
    if not base.exists():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        if not (d / "pack.json").exists() or not (d / "items.csv").exists():
            continue
        try:
            spec = _spec(d)
            items = _items(d, spec)
        except (CheckError, OSError, json.JSONDecodeError, KeyError):
            continue
        out.append({"id": d.name, "title": spec.get("title") or d.name, "items": len(items),
                    "checked": len(_current(home, d.name))})
    return out


def _pack_dir(home: Path, pack: str) -> Path:
    if not re.match(r"^\w[\w.-]*$", pack or ""):
        raise CheckError("bad pack name")
    d = root(home).resolve() / pack
    if not d.is_dir() or pack not in {p["id"] for p in packs(home)}:
        raise CheckError(f"no check pack {pack!r}")
    return d


def _digest(d: Path) -> str:
    h = hashlib.sha256()
    for name in ("pack.json", "items.csv"):
        h.update((d / name).read_bytes())
    return "sha256:" + h.hexdigest()


def _current(home: Path, pack: str) -> dict[str, dict]:
    f = _state_file(home, pack)
    out: dict[str, dict] = {}
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    out[rec["item"]] = rec
    return out


def _mark(text: str, words: str, occurrence: str | None) -> list[int] | None:
    """Where the words a reading is about sit in the text, or None."""
    if not words:
        return None
    n = int(occurrence) if occurrence and occurrence.strip().isdigit() else 1
    at = -1
    for _ in range(max(1, n)):
        at = text.find(words, at + 1)
        if at < 0:
            return None
    return [at, at + len(words)]


def load(home: Path, pack: str) -> dict[str, Any]:
    """The pack as the browser sees it. The control column is never in it."""
    d = _pack_dir(home, pack)
    spec = _spec(d)
    guide = ""
    if spec.get("guide"):
        g = (d / spec["guide"]).resolve()
        if g.is_relative_to(d.resolve()) and g.is_file():
            guide = g.read_text(encoding="utf-8")
    items = []
    for r in _items(d, spec):
        text = r[spec["text_field"]]
        items.append({
            "id": r[spec["id_field"]], "text": text, "proposal": r[spec["proposal_field"]],
            "mark": _mark(text, r.get(spec.get("mark_field") or "", ""),
                          r.get(spec.get("occurrence_field") or "")),
            "context": [[c, r[c]] for c in spec.get("context_fields", [])],
            "group": r[spec["group_field"]] if spec.get("group_field") else ""})
    current = {k: {"verdict": v["verdict"], "correction": v.get("correction", ""), "by": v["by"],
                   "at": v["at"]} for k, v in _current(home, pack).items()}
    return {"id": pack, "title": spec.get("title") or pack, "guide": guide, "digest": _digest(d),
            "has_controls": bool(spec.get("control_field")), "items": items, "current": current}


def save(home: Path, payload: dict[str, Any]) -> dict[str, Any]:
    pack = payload.get("pack", "")
    d = _pack_dir(home, pack)
    spec = _spec(d)
    by = (payload.get("by") or "").strip()
    if not by:
        raise CheckError("a checker name is required; an unattributed check cannot be audited")
    ids = {r[spec["id_field"]] for r in _items(d, spec)}
    item = payload.get("item", "")
    if item not in ids:
        raise CheckError("that item is not in the pack")
    verdict = payload.get("verdict", "")
    if verdict not in VERDICTS:
        raise CheckError(f"verdict must be one of {', '.join(VERDICTS)}")
    try:
        seconds = round(min(max(float(payload.get("seconds") or 0), 0.0), 3600.0), 1)
    except (TypeError, ValueError):
        seconds = 0.0
    correction = str(payload.get("correction") or "")[:2000]
    rec = {"item": item, "verdict": verdict, "correction": correction, "by": by,
           "seconds": seconds, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "pack_digest": _digest(d)}
    f = _state_file(home, pack)
    with _LOCK:
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return {"saved": item, "checked": len(_current(home, pack)), "items": len(ids)}


def export(home: Path, pack: str) -> dict[str, Any]:
    """One row per item with the verdict, and a summary of how the checking went."""
    d = _pack_dir(home, pack)
    spec = _spec(d)
    rows = _items(d, spec)
    current = _current(home, pack)
    out = (d / (spec.get("export") or "checks.csv")).resolve()
    if not out.is_relative_to(d.resolve()):
        raise CheckError("export must stay inside the pack directory")
    extra = ["verdict", "correction", "checked_by", "seconds"]
    header = [f for f in rows[0] if f not in extra] + extra if rows else extra
    control = spec.get("control_field")
    caught = missed = controls = 0
    seconds: list[float] = []
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            rec = current.get(r[spec["id_field"]])
            row = dict(r)
            if rec:
                row.update({"verdict": rec["verdict"], "correction": rec.get("correction", ""),
                            "checked_by": rec["by"], "seconds": rec.get("seconds", "")})
                seconds.append(float(rec.get("seconds") or 0))
                if control and str(r.get(control, "")).strip() in ("1", "true", "yes"):
                    controls += 1
                    caught += rec["verdict"] == "wrong"
                    missed += rec["verdict"] == "right"
            w.writerow(row)
    summary = {
        "items": len(rows), "checked": len(current),
        "verdicts": {v: sum(1 for x in current.values() if x["verdict"] == v) for v in VERDICTS},
        "median_seconds": round(statistics.median(seconds), 1) if seconds else None,
        "under_3_seconds": sum(1 for s in seconds if s < FAST_SECONDS),
    }
    if control:
        summary["controls"] = {"checked": controls, "caught": caught, "passed_as_right": missed}
    (d / "checks_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {"written": str(out), "checked": len(current), "items": len(rows), "summary": summary}
