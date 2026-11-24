# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0
"""Label mode: mark the parts of a text, one item at a time.

A **label pack** is a directory holding two files:

* ``pack.json``::

      {"schema": "arche.label_pack.v1",
       "title": "G0b addresses",
       "text_field": "address",            # the column a person labels
       "id_field": "id",
       "labels": [{"key": "road", "name": "Road", "hotkey": "r"}, ...],
       "guide": "LABELLING.md",            # optional, shown beside the item
       "group_field": "country",           # optional, a column to filter by
       "export": "labels.csv"}             # optional, where Export writes

* ``items.csv``: one row per item, with the id and text columns and any others,
  which are carried into the export untouched.

A person selects a stretch of the text and presses a label's key. Each save
records the whole item (its spans and whether it was skipped) as one appended
line in ``<studio home>/_studio/labels/<pack>.jsonl``, with who and when. The
latest line per item is the standing label; earlier lines are its history. The
pack itself is never written to.

Export writes one row per item: the item's own columns, one column per label
(the span texts in reading order, joined by a space), ``skip`` and
``labelled_by``. Nothing a model produced is ever shown in this mode: a label
pack is for gold data, and gold is only gold if the person did not see a guess.

Label packs live under ``<studio home>/label_packs`` (``ARCHE_LABEL_PACKS``
overrides it), so a pack built from data that must not enter a repository can
sit outside one.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "arche.label_pack.v1"
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_LOCK = threading.Lock()


class LabelError(ValueError):
    """A label pack or a label that cannot be accepted."""


def root(home: Path) -> Path:
    env = os.environ.get("ARCHE_LABEL_PACKS")
    return Path(env).expanduser() if env else home / "label_packs"


def _state_file(home: Path, pack: str) -> Path:
    return home / "_studio" / "labels" / f"{pack}.jsonl"


def _spec(directory: Path) -> dict[str, Any]:
    spec = json.loads((directory / "pack.json").read_text(encoding="utf-8"))
    if spec.get("schema") != SCHEMA:
        raise LabelError(f"{directory.name}: pack.json schema must be {SCHEMA}")
    labels = spec.get("labels") or []
    if not labels:
        raise LabelError(f"{directory.name}: a label pack needs at least one label")
    keys, hotkeys = set(), set()
    for lab in labels:
        key, hot = lab.get("key", ""), lab.get("hotkey", "")
        if not _KEY_RE.match(key) or key in keys or key == "skip":
            raise LabelError(f"{directory.name}: bad or repeated label key {key!r}")
        if len(hot) != 1 or hot in hotkeys or hot in "xjk":
            raise LabelError(f"{directory.name}: label {key!r} needs its own one-key hotkey "
                             "(x, j and k are taken)")
        keys.add(key)
        hotkeys.add(hot)
    for f in ("text_field", "id_field"):
        if not spec.get(f):
            raise LabelError(f"{directory.name}: pack.json needs {f}")
    if "group_field" in spec and not isinstance(spec["group_field"], str):
        raise LabelError(f"{directory.name}: group_field names one column")
    return spec


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
        except (LabelError, OSError, json.JSONDecodeError, KeyError):
            continue
        done = _current(home, d.name)
        out.append({"id": d.name, "title": spec.get("title") or d.name,
                    "items": len(items), "labelled": len(done)})
    return out


def _pack_dir(home: Path, pack: str) -> Path:
    # A pack is named by one directory entry of the root, never a path. The
    # entry may be a symlink to a pack kept elsewhere (data that must not sit
    # in a repository), so the name is checked, not the resolved target.
    if not re.match(r"^\w[\w.-]*$", pack or ""):
        raise LabelError("bad pack name")
    d = root(home).resolve() / pack
    if not d.is_dir():
        raise LabelError(f"no label pack {pack!r}")
    if pack not in {p["id"] for p in packs(home)}:
        raise LabelError(f"{pack!r} is not a label pack on offer")
    return d


def _items(d: Path, spec: dict) -> list[dict[str, str]]:
    with (d / "items.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r[spec["id_field"]] for r in rows]
    if len(set(ids)) != len(ids):
        raise LabelError(f"{d.name}: item ids are not unique")
    for r in rows:
        for f in (spec["text_field"], spec.get("group_field")):
            if f and f not in r:
                raise LabelError(f"{d.name}: items.csv has no {f!r} column")
    return rows


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


def load(home: Path, pack: str) -> dict[str, Any]:
    d = _pack_dir(home, pack)
    spec = _spec(d)
    items = _items(d, spec)
    guide = ""
    if spec.get("guide"):
        g = (d / spec["guide"]).resolve()
        if g.is_relative_to(d.resolve()) and g.is_file():
            guide = g.read_text(encoding="utf-8")
    current = _current(home, pack)
    return {"id": pack, "title": spec.get("title") or pack, "labels": spec["labels"],
            "guide": guide, "digest": _digest(d),
            "items": [{"id": r[spec["id_field"]], "text": r[spec["text_field"]],
                       "group": r[spec["group_field"]] if spec.get("group_field") else ""}
                      for r in items],
            "current": {k: {"spans": v["spans"], "skip": v["skip"], "by": v["by"],
                            "at": v["at"]} for k, v in current.items()}}


def save(home: Path, payload: dict[str, Any]) -> dict[str, Any]:
    pack = payload.get("pack", "")
    d = _pack_dir(home, pack)
    spec = _spec(d)
    by = (payload.get("by") or "").strip()
    if not by:
        raise LabelError("a labeller name is required; an unattributed label cannot be audited")
    items = {r[spec["id_field"]]: r[spec["text_field"]] for r in _items(d, spec)}
    item = payload.get("item", "")
    if item not in items:
        raise LabelError("that item is not in the pack")
    text, keys = items[item], {lab["key"] for lab in spec["labels"]}
    spans = []
    for s in payload.get("spans") or []:
        start, end, key = int(s["start"]), int(s["end"]), s["label"]
        if key not in keys:
            raise LabelError(f"unknown label {key!r}")
        if not 0 <= start < end <= len(text):
            raise LabelError("a span lies outside the text")
        spans.append({"start": start, "end": end, "label": key})
    spans.sort(key=lambda s: (s["start"], s["end"]))
    for a, b in zip(spans, spans[1:], strict=False):
        if b["start"] < a["end"]:
            raise LabelError("spans overlap; a stretch of text has one label")
    rec = {"item": item, "spans": spans, "skip": bool(payload.get("skip")), "by": by,
           "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "pack_digest": _digest(d)}
    f = _state_file(home, pack)
    with _LOCK:
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    done = _current(home, pack)
    return {"saved": item, "labelled": len(done), "items": len(items)}


def export(home: Path, pack: str) -> dict[str, Any]:
    d = _pack_dir(home, pack)
    spec = _spec(d)
    rows = _items(d, spec)
    current = _current(home, pack)
    keys = [lab["key"] for lab in spec["labels"]]
    out = (d / (spec.get("export") or "labels.csv")).resolve()
    if not out.is_relative_to(d.resolve()):
        raise LabelError("export must stay inside the pack directory")
    fields = list(rows[0].keys()) if rows else []
    header = fields + [k for k in keys if k not in fields] + ["skip", "labelled_by"]
    written = 0
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            rec = current.get(r[spec["id_field"]])
            row = dict(r)
            if rec:
                text = r[spec["text_field"]]
                for k in keys:
                    row[k] = " ".join(text[s["start"]:s["end"]].strip()
                                      for s in rec["spans"] if s["label"] == k)
                row["skip"] = "x" if rec["skip"] else ""
                row["labelled_by"] = rec["by"]
                written += 1
            w.writerow(row)
    return {"written": str(out), "labelled": written, "items": len(rows)}
